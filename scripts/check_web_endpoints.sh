set -e

host='localhost:1136'

routes="
/
/ngrams
/ngrams?query=trump
"
#/host
#/host?host=nytimes.com
#/metahtml
#/metahtml?id=1

failed=false
for route in $routes; do
    printf "[testing] $route \r"

    if curl -s --fail "http://$host/$route" > /dev/null; then
        echo '[pass]   '
    else
        echo '[fail]   '
        failed=true
    fi
done

if [ "$failed" = true ]; then
    exit 1
fi
