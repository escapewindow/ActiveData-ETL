cd /home/ec2-user/ActiveData-ETL/


git pull origin push-to-es6
export PYTHONPATH=.:vendor

~/pypy/bin/pypy activedata_etl/push_to_es.py --settings=resources/settings/staging/push_to_es.json


