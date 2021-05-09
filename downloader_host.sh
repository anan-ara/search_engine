#!/bin/sh

# load environment variables
while read var; do
    export $var
done < .env.prod

# generate a unique hashid
hashid=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)

# build the docker container
cd services/downloader_host
docker build -t novichenko/downloader_host .

# launch the docker container
hostname=$1
echo "hostname=$1"
docker run -d "--name=downloader_host_$hashid" --network=novichenko novichenko/downloader_host --db=postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/$POSTGRES_DB "--url_pattern=$1/*"

