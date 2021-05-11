#!/usr/bin/python3
'''
'''

# the sys import is needed so that we can import from the current project
import sys
sys.path.append('.')
import metahtml

# load imports
import gzip
import json
import sqlalchemy
import tempfile
import traceback
from warcio.archiveiterator import ArchiveIterator
import wget
import pspacy


def process_all_warcs_from_url(connection, cc_url):
    with tempfile.TemporaryDirectory() as tempdir:
        logging.info('downloading url '+cc_url+' to '+tempdir)

        # attempt to download the file with an exponential backoff
        delay = 60
        while True:
            try:
                cc_path = wget.download(cc_url, out=tempdir)
                break
            except ConnectionResetError:
                logging.info('ConnectionResetError')
                sleep(delay)
                delay*=2

        # process the downloaded archive
        with gzip.open(cc_path, 'rt') as f:
            for line in f:
                prefix = 'https://commoncrawl.s3.amazonaws.com/'
                warc_url = prefix+line.strip()
                logging.info("warc_url="+warc_url)
                process_warc_from_url(connection, warc_url)


def process_warc_from_url(connection, warc_url):
    '''
    FIXME:
    ideally, this function would be wrapped in a transaction;
    but this causes deadlocks when it is run concurrently with other instances of itself
    '''
    # create a new entry in the source table for this bulk insertion
    try:
        sql = sqlalchemy.sql.text('''
        INSERT INTO source (name) VALUES (:name) RETURNING id;
        ''')
        res = connection.execute(sql,{'name':warc_url})
        id_source = res.first()['id']
        logging.debug('id_source='+str(id_source))

    # if an entry already exists in source,
    # then we have already inserted this warc and can safely skip the file
    except sqlalchemy.exc.IntegrityError:
        logging.info('skipping warc_url='+warc_url)
        return

    # process the warc file in a temporary directory;
    # the downloaded warc file will be stored in this directory and automatically deleted
    with tempfile.TemporaryDirectory() as tempdir:
        logging.info('downloading url '+warc_url+' to '+tempdir)
        warc_path = wget.download(warc_url, out=tempdir)
        process_warc_from_disk(connection, warc_path, id_source)

    # finished loading the file, so update the source table
    sql = sqlalchemy.sql.text('''
    UPDATE source SET finished_at=now() where id=:id;
    ''')
    res = connection.execute(sql,{'id':id_source})


def process_warc_from_disk(connection, warc_path, id_source, batch_size=100):
    '''
    '''
    with open(warc_path, 'rb') as stream:

        # for efficiency, we will not insert items into the db one at a time;
        # instead, we add them to the batch list,
        # and then bulk insert the batch list when it reaches len(batch)==batch_size
        batch = []

        for record in ArchiveIterator(stream):

            # WARC files contain many entries;
            # we only care about HTTP200 status code responses
            if record.rec_type == 'response':

                # extract the information from the warc archive
                url = record.rec_headers.get_header('WARC-Target-URI')
                accessed_at = record.rec_headers.get_header('WARC-Date')
                html = record.content_stream().read()
                logging.debug("url="+url)

                # extract the meta
                try:
                    meta = metahtml.parse(html, url)
                    try:
                        pspacy_title = pspacy.lemmatize(meta['language']['best']['value'], meta['title']['best']['value'])
                        pspacy_content = pspacy.lemmatize(meta['language']['best']['value'], meta['title']['best']['value'])
                    except TypeError:
                        pspacy_title = None
                        pspacy_content = None

                # if there was an error in metahtml, log it
                except Exception as e:
                    logging.warning('url='+url+' exception='+str(e))
                    meta = {
                        'exception' : {
                            'str(e)' : str(e),
                            'type' : type(e).__name__,
                            'location' : 'metahtml',
                            'traceback' : traceback.format_exc()
                            }
                        }
                    pspacy_title = None
                    pspacy_content = None

                # add the results to the batch
                meta_json = json.dumps(meta, default=str)
                batch.append({
                    'accessed_at' : accessed_at,
                    'id_source' : id_source,
                    'url' : url,
                    'jsonb' : meta_json,
                    'pspacy_title' : pspacy_title,
                    'pspacy_content' : pspacy_content
                    })

            # bulk insert the batch
            if len(batch)>=batch_size:
                bulk_insert(batch)
                batch = []

        # we have finished looping over the archive;
        # we should bulk insert everything in the batch list that hasn't been inserted
        if len(batch)>0:
            bulk_insert(batch)


def bulk_insert(batch):
    try:
        logging.info('bulk_insert '+str(len(batch))+' rows')
        keys = ['accessed_at', 'id_source', 'url', 'jsonb']
        sql = sqlalchemy.sql.text(
            'INSERT INTO metahtml ('+','.join(keys)+',title,content) VALUES'+
            ','.join(['(' + ','.join([f':{key}{i}' for key in keys]) + f",to_tsvector('simple',:pspacy_title{i}),to_tsvector('simple',:pspacy_content{i})" + ')' for i in range(len(batch))])
            )
        res = connection.execute(sql,{
            key+str(i) : d[key]
            for key in keys + ['pspacy_title','pspacy_content']
            for i,d in enumerate(batch)
            })
    except Exception as e:
        logging.error('failed to insert:'+str(e))
        pass


if __name__ == '__main__':
    # process command line args
    import argparse
    parser = argparse.ArgumentParser(description='''
    Insert the warc file into the database.
    ''')
    parser.add_argument('--warc', help='warc file to insert into the db; may be either a file path or a url')
    parser.add_argument('--cc_url')
    parser.add_argument('--db', default='postgresql:///')
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO)

    # create database connection
    engine = sqlalchemy.create_engine(args.db, connect_args={
        'application_name': 'metahtml',
        'connect_timeout': 60*60
        })
    connection = engine.connect()

    if args.warc:
        process_warc_from_url(connection,args.warc)
