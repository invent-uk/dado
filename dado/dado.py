#!/usr/bin/env python3

import os.path
import os
import yaml
import ffmpeg
import argparse
import logging
import importlib
import re
import time
from datetime import datetime, timedelta
from motiondetection import MotionDetection
from util import plural
from pprint import pprint as pprint


class Dado:
    """Provides a daemon that automatically downloads dashcam recordings.

    The daemon interacts with a camera device over a network, identifies
    the important recordings using motion detection and then downloads
    and merges them based on the configuration.
    """

    def __init__(self, config):
        with open(config, 'r') as file:
            self.config = yaml.load(file, Loader=yaml.SafeLoader)

        numeric_level = getattr(logging, self.config.get('log_level', 'info').upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % self.config.get('log_level', 'info'))
        logging.basicConfig(
            format='%(asctime)s %(levelname)-8s %(message)s',
            level=numeric_level,
            datefmt='%Y-%m-%d %H:%M:%S')
        global logger
        logger = logging.getLogger(__name__)

        logger.info("Dado started..")

        self.state = {}

        camera_module = importlib.import_module(self.config.get('camera').get('module'))
        Camera_class = getattr(camera_module, self.config.get('camera').get('class'))
        self.camera = Camera_class(self.config.get('camera'))
        self.motion = MotionDetection(self.config.get('motion_detection'), self.state)

    def run_daemon(self):
        while True:
            # try:
            if True:
                if self.camera.initiate():

                    if self.config.get('download_events'):
                        self.download_events()

                    if self.config.get('download_recordings'):
                        (filtered_recordings, requested_sequences) = self.identify_recordings()
                        self.download_recordings(requested_sequences)

                        if self.config.get('force_download_all'):
                            logger.info("Processing forced download of all recordings..")
                            all_recordings = [{"recordings": filtered_recordings}]
                            self.add_paths(all_recordings[0]['recordings'], "original_filename")
                            self.download_videos(all_recordings)

            # except Exception as e:
            #     logger.error("Error encountered in the belt and braces exception handler: {}".format(e))

            logger.info("Sleeping for {} seconds".format(self.config.get('sleep_interval')))
            logger.info("--------------------------------------------------")

            time.sleep(int(self.config.get('sleep_interval')))

    def download_events(self):
        event_list = self.camera.list_events()
        if event_list and len(event_list) > 0:
            self.camera.prepare_events(event_list)
            total = len(event_list)
            logger.info("{} event{} on device".format(total, plural(total), len(event_list)))
            self.prepare_recordings(event_list)
            self.add_paths(event_list, "event_filename")
            self.camera.download_files(event_list, "filename", "event_filename")

    def identify_recordings(self):
        all_recordings = self.camera.list_recordings()

        if all_recordings and len(all_recordings) > 0:
            self.camera.prepare_recordings(all_recordings)
            filtered_recordings = self.filter_processed(all_recordings)
            total = len(filtered_recordings)
            self.prepare_recordings(filtered_recordings)
            logger.info("{} file{} on device of which {} are to be processed".format(total, plural(total), len(filtered_recordings)))

            if len(filtered_recordings) > 0:
                logger.info("The oldest recording on the device is: {}".format(filtered_recordings[0]['start_timestamp']))
            requested_sequences = []

            if self.config.get('process_manual_requests'):
                logger.info("Processing manual requests..")

                manual_requests = self.find_manual_requests()
                requested_sequences.extend(manual_requests)

            if self.config.get('process_motion_detection'):
                logger.info("Processing motion detection..")

                self.add_paths(filtered_recordings, "thumbnail_filename")
                download_list = self.camera.download_files(filtered_recordings, "thumbnail", "thumbnail_filename")
                self.motion.calculate_differences(download_list, "thumbnail_filename")
                requested_sequences.extend(self.motion.identify_requests(download_list))

            self.match_recordings(requested_sequences, all_recordings)
            self.remove_empty_requests(requested_sequences)

        return (filtered_recordings, requested_sequences)

    def download_recordings(self, requested_sequences):
        downloaded_requests = []
        for requested_sequence in requested_sequences:
            self.add_paths(requested_sequence['recordings'], "original_filename")

            downloaded_requests.append(self.download_videos(requested_sequence))

            if self.config.get('merge_videos'):
                self.merge_recordings(requested_sequence)

            self.remove_successful_request(requested_sequence)

    def remove_empty_requests(self, requested_recordings):
        requested_recordings[:] = [tup for tup in requested_recordings if not len(tup['recordings']) == 0]

    def prepare_recordings(self, list):
        for item in list:
            self.add_local_metadata(item)

    def add_local_metadata(self, item):
        item['start_timestamp'] = item['startdatetime'].strftime(self.config['recording_timestamp'])
        item['end_timestamp'] = item['enddatetime'].strftime(self.config['recording_timestamp'])
        item['start_time'] = item['startdatetime'].strftime(self.config['recording_time'])
        item['end_time'] = item['enddatetime'].strftime(self.config['recording_time'])
        item['directory_timestamp'] = item['startdatetime'].strftime(self.config['directory_timestamp'])

    def add_paths(self, list, key):
        for item in list:
            self.add_path(item, key)

    def add_path(self, item, key):
        item[key] = os.path.join(self.config['output_root'], self.config[key].format(**item))

    def already_processed(self, item):
        return item['startdatetime'] <= self.state['last_image_processed']['enddatetime']

    def filter_processed(self, list):
        filtered = []
        for item in list:
            if 'last_image_processed' not in self.state or not self.already_processed(item):
                filtered.append(item)
        return filtered

    def match_recordings(self, requested_times, list):
        for requested_time in requested_times:
            matching_recordings = []
            for recording in list:
                if recording['enddatetime'] >= requested_time['startdatetime'] \
                   and recording['startdatetime'] <= requested_time['enddatetime']:
                    self.add_local_metadata(recording)
                    matching_recordings.append(recording)

            if len(matching_recordings) > 0:
                if "start" not in requested_time:
                    requested_time['start'] = matching_recordings[0]
                if "end" not in requested_time:
                    requested_time['end'] = matching_recordings[-1]
                logger.debug("Requesting download of {} recordings from {} to {}".format(len(matching_recordings),
                                                                                         requested_time['start']['start_timestamp'],
                                                                                         requested_time['end']['end_time']))
            else:
                logger.info("No recordings found matching manual request")
            requested_time['recordings'] = matching_recordings

    def download_videos(self, request):
        request['downloaded'] = self.camera.download_files(request['recordings'], "name", "original_filename")
        logger.debug("Downloaded {} recordings".format(len(request['downloaded'])))

        return request

    def merge_recordings(self, request):
        self.add_path(request, "recording_filename")

        recordings = request['recordings']

        list_file = request['recording_filename'] + self.config['list_extension']
        final_file = request['recording_filename'] + self.config['recording_extension']
        logger.info("Merging recordings for {}".format(final_file))

        path = os.path.dirname(list_file)
        if not os.path.exists(path):
            logger.debug("Making dir {}".format(path))
            os.makedirs(path)

        with open(list_file, 'w') as f:
            for recording in recordings:
                fullpath = os.path.abspath(recording['original_filename'])
                f.write("file '{}'\n".format(fullpath))

        if os.path.isfile(final_file):
            os.remove(final_file)
        try:
            ffmpeg.input(list_file, format='concat', safe=0).output(final_file, c='copy') \
                .global_args('-loglevel', self.config.get('ffmpeg_log_level', 'info')) \
                .global_args('-y').run()
            os.remove(list_file)
            request['merge_status'] = True
        except Exception as e:
            logger.error("Error merging recordings with ffmpeg: {}".format(e))
            request['merge_status'] = False

    def remove_successful_request(self, item):
        if item['event'] == 'manual':
            if os.path.isfile(item['request_file']):
                os.remove(item['request_file'])

    def iterate_path(self, directory, extension):
        logger.debug("Iterate path: {} to find files with extension {}".format(directory, extension))
        list = []
        extension = extension.lower()
        for dirpath, dirnames, files in os.walk(directory):
            for name in files:
                if extension and name.lower().endswith(extension):
                    list.append({"dir": dirpath, "filename": name})
        return list

    def find_manual_requests(self):
        requests = []
        list = self.iterate_path(self.config['output_root'], self.config['manual_request_extension'])
        # Data comes back as:
        #    [{'dir': 'cctv/dashcam', 'filename': '2020-05-14-1200-1210.request'}]
        for item in list:
            match = re.search(self.config['manual_request_regex'] + self.config['manual_request_extension'], item['filename'])
            if match:
                match.group(2)
                start_time = "{}-{}".format(match.group(1), match.group(2))
                end_time = "{}-{}".format(match.group(1), match.group(3))
                item['event'] = "manual"
                item['request_file'] = os.path.join(item['dir'], item['filename'])
                item['startdatetime'] = datetime.strptime(start_time, self.config['recording_timestamp'])
                item['enddatetime'] = datetime.strptime(end_time, self.config['recording_timestamp'])
                if item['enddatetime'] < item['startdatetime']:
                    # If end time is before start time then we must have bridged midnight
                    # so the end time should be moved to the next day.
                    item['startdatetime'] = item['startdatetime'] + timedelta(days=1)
                requests.append(item)

        return requests


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="Specify the relative path to the config file, defaults to config.yaml", default="config.yaml")
    args = parser.parse_args()

    dado = Dado(args.config)
    dado.run_daemon()
