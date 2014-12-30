# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import unicode_literals
import StringIO
import zipfile

import requests

from pyLibrary import aws
from pyLibrary import convert
from pyLibrary.debugs import startup
from pyLibrary.debugs.logs import Log
from pyLibrary.structs import wrap, Struct
from pyLibrary.thread.threads import Thread
from pyLibrary.times.dates import Date


DEBUG = True
DEBUG_SHOW_NO_LOG = False


def process_pulse_block(source_key, source, dest_bucket):
    """
    SIMPLE CONVERT pulse_block INTO S3 LOGFILES
    PREPEND WITH ETL HEADER AND PULSE ENVELOPE
    """
    for i, line in enumerate(source.read().split("\n")):
        envelope = convert.json2value(line)
        if envelope._meta:
            pass
        elif envelope.locale:
            if DEBUG:
                Log.note("Line {{index}}: found pulse message stripped of envelope", {"index": i})
            envelope = Struct(data=envelope)
        elif envelope.source:
            continue
        elif envelope.pulse:
            if DEBUG:
                Log.note("Line {{index}}: found pulse array", {"index": i})
            # FEED THE ARRAY AS A SEQUENCE OF LINES FOR THIS METHOD TO CONTINUE PROCESSING
            def read():
                return convert.unicode2utf8("\n".join(convert.value2json(p) for p in envelope.pulse))

            temp = Struct(read=read)

            return process_pulse_block(source_key, temp, dest_bucket)
        else:
            Log.error("Line {{index}}: Do not know how to handle line\n{{line}}", {"line": line, "index": i})

        file_num = 0
        for name, url in envelope.data.blobber_files.items():
            try:
                if "structured" in name and name.endswith(".log"):
                    log_content = requests.get(url).content
                    dest_key, dest_etl = etl_key(envelope, source_key, name, file_num)

                    dest_bucket.write(
                        dest_key + ".json.zip",
                        new_zipfile(
                            dest_key + ".json",
                            convert.unicode2utf8(convert.value2json(dest_etl)) + b"\n" +
                            convert.unicode2utf8(line) + b"\n" +
                            log_content
                        )
                    )
                    file_num += 1
            except Exception, e:
                Log.error("Problem processing {{url}}", {"url": url}, e)

        if not file_num and DEBUG_SHOW_NO_LOG:
            Log.note("No structured log {{json}}", {"json": envelope.data})


def etl_key(envelope, source_key, name, file_num):
    dest_key = \
        unicode(envelope.data.builddate) + "." + \
        envelope.data.revision[:12].lower() + "." + \
        unicode(envelope.data.job_number) + "." + \
        unicode(Date(envelope.data.timestamp).milli)[:-3] + "." + \
        unicode(file_num)

    if envelope.data.etl:
        dest_etl = wrap({"id": file_num, "name": name, "source": envelope.data.etl, "type": "join"})
    else:
        if source_key.endswith(".json"):
            source_key = source_key[:-5]

        dest_etl = wrap({
            "id": file_num,
            "name": name,
            "source": {
                "id": source_key
            },
            "type": "join"
        })
    return dest_key, dest_etl


def new_zipfile(filename, content):
    buff = StringIO.StringIO()
    archive = zipfile.ZipFile(buff, mode='w')
    archive.writestr(filename, content)
    archive.close()
    return buff.getvalue()


def loop(work_queue, conn, dest, please_stop):
    while not please_stop:
        todo = work_queue.pop()
        if todo == None:
            return

        with conn.get_bucket(todo.bucket) as source:
            try:
                process_pulse_block(todo.key, source.get_key(todo.key + ".json"), dest)
                work_queue.commit()
            except Exception, e:
                Log.warning("could not processs {{key}}", {"key": todo.key}, e)


def main():
    try:
        settings = startup.read_settings()
        Log.start(settings.debug)

        with startup.SingleInstance(flavor_id=settings.args.filename):
            with aws.Queue(settings.work_queue) as work_queue:
                with aws.s3.Connection(settings.aws) as conn:
                    with aws.s3.Bucket(settings.destination) as dest:
                        thread = Thread.run("main_loop", loop, work_queue, conn, dest)
                        Thread.wait_for_shutdown_signal(thread.please_stop)
                        thread.stop()
                        thread.join()
    except Exception, e:
        Log.error("Problem with etl", e)
    finally:
        Log.stop()


if __name__ == "__main__":
    main()