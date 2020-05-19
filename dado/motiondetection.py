#!/usr/bin/env python3

import os.path
import os
import logging
import datetime

import numpy as np
from skimage import io

logger = logging.getLogger(__name__)

STATE_IDLE = 0
STATE_COUNTING_IN = 1
STATE_RECORDING = 2
STATE_COUNTING_OUT = 3


class MotionDetection:
    """A class to provide basic change detection in a list of images."""

    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.request_list = []

        self.state_switcher = {
                STATE_IDLE: self.idle,
                STATE_COUNTING_IN: self.counting_in,
                STATE_RECORDING: self.recording,
                STATE_COUNTING_OUT: self.counting_out,
        }

    def image_triggered(self, item):
        return item.get('image_diff', 0) > self.config['sensitivity']

    def check_count_in_threshold(self, item):
        if self.count >= self.config['start_count']:
            self.status = STATE_RECORDING
            logger.info("Detected a recording starting at {}".format(item['start_timestamp']))

    def check_count_out_threshold(self, item):
        if self.count >= self.config['stop_count']:
            logger.info("Detected a recording finishing at {}".format(item['start_timestamp']))
            self.status = STATE_IDLE
            self.request_recording(item)

    def idle(self, item):
        if self.image_triggered(item):
            self.status = STATE_COUNTING_IN
            self.count = 0
            self.trigger_start_image = item
            self.check_count_in_threshold(item)

    def counting_in(self, item):
        if self.image_triggered(item):
            self.count += 1
            self.check_count_in_threshold(item)
        else:
            self.status = STATE_IDLE

    def recording(self, item):
        if not self.image_triggered(item):
            self.status = STATE_COUNTING_OUT
            self.count = 0

    def counting_out(self, item):
        if not self.image_triggered(item):
            self.count += 1
            self.check_count_out_threshold(item)
        else:
            self.status = STATE_RECORDING

    def request_recording(self, item):
        logger.info("Requesting recording {} to {}".format(self.trigger_start_image['startdatetime'], item['enddatetime']))
        self.request_list.append({"start": self.trigger_start_image,
                                  "end": item,
                                  "startdatetime": self.trigger_start_image['startdatetime'],
                                  "enddatetime": item['enddatetime'],
                                  "event": "motion"})

    def calculate_differences(self, list, field):
        last_image = None
        this_image = None
        for item in list:
            if not self.state.get('last_image_processed') or item['startdatetime'] >= self.state.get('last_image_processed')['enddatetime']:
                if os.path.isfile(item[field]) and os.stat(item[field]).st_size > 0:
                    try:
                        this_image = io.imread(item[field])
                    except ValueError as e:
                        logger.error("Error loading image for {}: {}".format(item[field], e))

                    if last_image is not None and this_image is not None:
                        try:
                            mse_val = round(MotionDetection.mse(last_image, this_image,), 1)
                            # logger.debug("Calculating mse for {} as {}".format(item[field], mse_val))
                            item['image_diff'] = mse_val
                        except ValueError as e:
                            logger.error("Error comparing images for {}: {}".format(item[field], e))
                            item['image_diff'] = 0
                    else:
                        item['image_diff'] = 0

                else:
                    logger.info("Skipping calculation as file does not exist or is empty for {}".format(item[field]))
                    item['image_diff'] = 0
            last_image = this_image

    def identify_requests(self, list):
        self.status = STATE_IDLE
        self.trigger_start_image = None
        self.count_threshold = None
        last = None
        self.request_list = []

        for item in list:
            func = self.state_switcher.get(self.status, "Invalid state, will crash")
            logger.debug("{} Event status: {}. Current image change from last image: {}".format(item['start_timestamp'], self.status, item.get('image_diff', 'None')))
            func(item)

            # Update the last processed state for the next run. Only do this when idle
            if self.status == STATE_IDLE and last and not self.image_triggered(item):
                self.state['last_image_processed'] = last

            # Split the recording if longer than the max. Update the state also to allow next run to continue from here
            if self.status == STATE_RECORDING and last:
                max = datetime.timedelta(seconds=self.config['maximum_video_length'])
                if item['enddatetime'] > self.trigger_start_image['startdatetime'] + max:
                    self.request_recording(last)
                    self.trigger_start_image = item
                    self.state['last_image_processed'] = last
            last = item
        return self.request_list

    @staticmethod
    def mse(imageA, imageB):
        """Compare image content to allow a difference number to be used as a trigger."""
        err = np.sum((imageA.astype("float") - imageB.astype("float")) ** 2)
        err /= float(imageA.shape[0] * imageA.shape[1])
        return err
