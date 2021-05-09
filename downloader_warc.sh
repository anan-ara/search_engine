#!/bin/sh

# load environment variables
while read var; do
    export $var
done < .env.prod

# generate a unique hashid
hashid=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)

# build the docker container
cd services/downloader_warc
docker build -t novichenko/downloader_warc .

warc=$1
name=$(basename $(dirname $warc))
echo "warc=$name"

# launch the docker container
docker run -d --name=metahtml_warc_$hashid --network=novichenko novichenko/downloader_warc --db=postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/$POSTGRES_DB "--warc=$warc"
