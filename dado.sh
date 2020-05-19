#!/bin/sh

if [ ! -e config.yaml ]
then
    echo "config.yaml not found. Copying sample into place."
    cp config.yaml.sample config.yaml
fi
./dado/dado.py
