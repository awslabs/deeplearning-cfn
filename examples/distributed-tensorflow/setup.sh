#!/bin/bash

pip uninstall -y numpy
pip install numpy==1.17.5
pip install awscli
pip install boto3
pip install ujson==1.35
pip install opencv-python==4.1.0.25
pip install Cython==0.28.4
pip uninstall -y pycocotools
git clone https://github.com/cocodataset/cocoapi.git $HOME/cocoapi
cd $HOME/cocoapi && git fetch origin 8c9bcc3cf640524c4c20a9c40e89cb6a2f2fa0e9
cd $HOME/cocoapi && git reset --hard 8c9bcc3cf640524c4c20a9c40e89cb6a2f2fa0e9
cd  $HOME/cocoapi/PythonAPI && make
pip install -e $HOME/cocoapi/PythonAPI
pip install matplotlib==3.0.3
pip install markdown==3.1

pip install -e $HOME/tensorpack
