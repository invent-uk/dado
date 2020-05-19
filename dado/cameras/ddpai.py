#!/usr/bin/env python3

import json
import requests
import os.path
import os
import logging
import re

from requests.adapters import HTTPAdapter
from datetime import datetime, timezone, timedelta
from operator import itemgetter
from json.decoder import JSONDecodeError

from util import plural

logger = logging.getLogger(__name__)

HTTP_DATE_FORMAT = "%a, %d %b %Y %H:%M:%S %Z"


class DDPAI:
    """A class to encapsulate the API functionality of a dashcam device."""

    def __init__(self, config):
        self.config = config
        self.sessionid = None

        # One session for the initial request, no retries quiet failure
        self.session = requests.Session()

        # One session for downloading images and videos, retry on failure
        self.session_reliable = requests.Session()
        self.session_reliable.mount(self.get_http_endpoint(), HTTPAdapter(max_retries=self.config['http_retries']))

    def get_http_endpoint(self):
        return "http://{}:{}".format(self.config['address'], self.config['port'])

    def get_api_url(self, action):
        return self.get_http_endpoint() + "/{}{}".format(self.config['api_path'], action)

    def get_download_url(self, filename):
        return self.get_http_endpoint() + "/{}".format(filename)

    def auth(self):
        (response, duration, ts) = self.request(self.get_api_url("API_RequestSessionID"), session=self.session)
        if response:
            data = self.json(response)
            self.sessionid = data.get('acSessionId', None)
            return True
        else:
            return False

    def requestcert(self):
        data = {"user": "admin",
                "password": "admin",
                "level": 0,
                "uid": "c95696e23897d9ca"}
        (response, duration, ts) = self.request(self.get_api_url("API_RequestCertificate"), method='POST', data=json.dumps(data))

    def settime(self):
        max_drift_seconds = self.config.get('time_set_max_drift', None)
        d = datetime.now(timezone.utc).astimezone()
        self.utcoffset = d.utcoffset() // timedelta(seconds=1)

        if max_drift_seconds and max_drift_seconds > 0:
            max_drift = timedelta(seconds=max_drift_seconds)
            now = datetime.now()
            (response, duration, ts) = self.request(self.get_api_url("API_SyncDate"), method="POST")

            drift = abs(ts - now)
            logger.info("Time on the device: {}".format(ts.strftime("%H:%M:%S")))
            logger.debug("Response time {}".format(duration))
            logger.debug("Calculated clock drift {}".format(drift))

            if drift > max_drift + duration:
                logger.info("Setting time due o drift of {}".format(drift))

                data = {"date": datetime.now().strftime(self.config['date_format']),
                        "imei": "0000000000000000",
                        "time_zone": self.utcoffset,
                        "format": self.config['internal_date_format'],
                        "lang": self.config['internal_language']}

                (response, duration, ts) = self.request(self.get_api_url("API_SyncDate"), method="POST", data=json.dumps(data))
                logger.debug(response.json())

    def json(self, response):
        try:
            data = json.loads(response.json()['data'])
        except (JSONDecodeError, AttributeError) as e:
            logger.error("Error decoding json: {}".format(e))
            if response:
                logger.debug(response.text)
            return None
        return data

    def request(self, url, method='GET', data='', session=None):
        logger.debug("Making request for: {}".format(url))

        if not session:
            session = self.session_reliable
        start = datetime.now()
        response = None
        timestamp = None
        headers = {}
        if self.sessionid:
            headers['sessionid'] = self.sessionid
        dict(cookies_are='working')
        try:
            response = self.session.request(method, url, data=data, headers=headers)
            timestamp = datetime.strptime(response.headers['Date'], HTTP_DATE_FORMAT)
        except requests.ConnectionError as e:
            logger.info("Camera not available")
            logger.debug("Error reported: {}".format(e))
        end = datetime.now()
        elapsed = end - start

        return (response, elapsed, timestamp)

    def list_recordings(self):
        logger.info("Querying camera for list of recordings..")

        (response, duration, ts) = self.request(self.get_api_url("APP_PlaybackListReq"), method='POST', data="{}")
        if response:
            data = self.json(response)
            if data:
                logger.info("{} file{} found in {:.2f}s".format(data['num'], plural(data['num']), duration.total_seconds()))
                return data.get('file')
        return None

    def list_events(self):
        logger.info("Querying camera for list of events..")

        (response, duration, ts) = self.request(self.get_api_url("APP_EventListReq"), method='POST', data="{}")
        if response:
            data = self.json(response)
            if data:
                logger.info("{} event{} found in {:.2f}s".format(data['num'], plural(data['num']), duration.total_seconds()))
                return data.get('event')
        return None

    def download_files(self, list, key, local_key):
        count = 1
        skipped = 0
        for file in list:
            filename = file[key]
            localfile = file[local_key]

            if os.path.isfile(localfile) and os.stat(localfile).st_size > 0:
                skipped += 1
        logger.info("{} file{} already downloaded. {} file{} remaining".format(skipped, plural(skipped), len(list) - skipped, plural(len(list) - skipped)))
        for file in list:
            filename = file[key]
            localfile = file[local_key]
            directory = os.path.dirname(localfile)
            if not os.path.exists(directory):
                logger.debug("Making dir {}".format(directory))

                os.makedirs(directory)
            if not os.path.isfile(localfile) or os.stat(localfile).st_size == 0:

                (response, duration, ts) = self.request(self.get_download_url(filename))
                if response:
                    logger.debug("{}/{}: Downloaded {} in {:.2f}s".format(count, len(list) - skipped, filename,  duration.total_seconds()))
                    with open(localfile, 'wb') as f:
                        f.write(response.content)
                else:
                    logger.error("Failed to download: {}".format(filename))
                count += 1
        return list

    def find_files(self, extension):
        path = os.path.join(self.config['output_root'], self.config['constant_path'])
        files = self.iterate_path(path, extension)
        return files

    def initiate(self):
        if self.auth():
            self.requestcert()
            if 'time_set' in self.config and self.config['time_set']:
                self.settime()
            return True
        else:
            return False

    def prepare_events(self, list):
        for event in list:
            if event.get('bvideoname', "") != "":
                event['filename'] = event['bvideoname']
                self.add_datetime_from_timestamp(event, startkey="bstarttime", endkey="bendtime")
            elif event.get('imgname', "") != "":
                event['filename'] = event['imgname']
                self.add_datetime_from_name(event, self.config['date_format'], "filename")

    def prepare_recordings(self, list):
        self.add_thumbnail(list)
        for item in list:
            self.add_datetime_from_timestamp(item)

        if self.config.get('sort_order', None):
            list.sort(key=itemgetter(self.config.get('sort_order')))
        return list

    def add_thumbnail(self, list):
        for item in list:
            item['thumbnail'] = item['name'].replace(".mp4", self.config['thumbnail_extension'])

    def add_datetime_from_name(self, item, format, key):
        num = "".join((re.findall("\\d+", item[key])))
        item['startdatetime'] = datetime.strptime(num, format)
        item['enddatetime'] = datetime.strptime(num, format)

    def add_datetime_from_timestamp(self, item, startkey="starttime", endkey="endtime"):
        # These timestamps seem to be advanced by the UTC offset, hence
        # reducing them by the offset calculated in settime()
        item['startdatetime'] = datetime.fromtimestamp(int(item[startkey]) - self.utcoffset)
        if endkey in item:
            item['enddatetime'] = datetime.fromtimestamp(int(item[endkey]) - self.utcoffset)
        else:
            item['enddatetime'] = item['startdatetime']

    def download_requests(self, listing, requested_times):
        for (start, finish) in requested_times:
            matching_recordings = []
            for recording in listing:
                if recording['enddatetime'] >= start['startdatetime'] and recording['startdatetime'] <= finish['enddatetime']:
                    matching_recordings.append(recording)
            logger.debug("Requesting download of {} recordings".format(len(matching_recordings)))
            downloaded = self.download_files(matching_recordings, "name", "local_original")
            logger.debug("Downloaded {} recordings".format(len(downloaded)))
        return downloaded
