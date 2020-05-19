
# Dado - Dashcam downloader

## Summary

Dado is a python script that automatically downloads dash cam recordings from a wifi connected camera.

## Aim

There are a number of dashcams on the market that support Wifi connectivity. Unfortunately many of these dashcams do not offer a method to download these recordings onto a computer, instead relying on an app to download video onto the user's phone when requested. This script is intended to fill that gap for a particular type of cameras, code submissions to support other cameras are welcome.

The script executes as a daemon, identifying dashcam recordings of interest using camera events and motion detection. Once the recordings are identified they are downloaded and then merged into longer videos using ffmpeg. The script will then sleep for 10 minutes before continuing where it left off. Motion detection is use to limit the download of recordings to those that take place when the vehicle is in use. This allows the camera to still be configured to record 24x7 without creating a constant saturation of the wifi link.

## Initial camera support

The code was written against an IRO A66 camera designed for a Tesla Model S AP1. There is no programming interface documentation available for this camera but inspiration was taken from the following page:

https://www.eionix.co.in/2019/10/10/reverse-engineer-ddpai-firmware.html

The code may support a whole range of DDPAI cameras without any modification.

Supported cameras:

| Type  | Model  | Notes |
|---|---|---|
| DDPAI  | IRO A66  | Supports events, recordings and time sync |

## Functionality

Dado can:
- Set the dashcam device clock
- Download video/images from events (G-sensor, photo button)
- Compare thumbnails for all videos to detect when the vehicle is in motion
- Download video segments and merge them into longer clips
- Allow the user to manually request the download of a time period

## Requirements

Dado requires python3. It is packaged to run under Docker although that is not a requirement.
The computer will need access to the camera over Wifi. The original camera tested provides an access point and requires devices to connect as Wifi clients. This can be done using either a Wifi interface directly connected to the computer or some kind of bridge.
For this script to function the dashcam needs to be powered most of the time as downloading videos over Wifi takes time. The storage device on the camera should be large enough that it covers the time period whilst the device is away from the computer running the script, this will ensure important events are not lost.

## Usage

1. Clone the Repository
2. Copy config.yaml.sample to config.yaml
3. Check the configuration matches your requirements
4. Modify docker-compose.yml to point to correct output path
5. Modify timezone in Dockerfile (line 5)
6. Execute: `docker-compose up -d`

### Motion detection

The motion detection is very simply and operates using a frame difference algorithm. It will need tuning to your situation. A threshold of around 1500 seems to be good enough to detect when the car is in motion. This is the `sensitivity` option in the config file.

### Manual requests

In order to request the script download a particular time period on the next pass an empty file needs to be written anywhere to the output directory structure. The time format is defined in the configuration file, by default it is:

`%Y-%m-%d-%H%M-%H%M.request`

For example:

`touch cctv/dashcam/2020-05-19-2000-2100.request`

### Problem determination

 If problems occur the logging can be increased within config.yaml to debug, this will give a lot more information about the background actions.

## Warning

Using this script may shorten the life of your dashcam as it will be doing a lot more work than it would have been otherwise. The camera will also use more power so please ensure there is a sufficient power supply to run it without causing issues with the functioning of the vehicle. As there is no official documentation covering camera APIs it is quite possible the camera will be damaged in some way by this script. Please consider this before downloading.
