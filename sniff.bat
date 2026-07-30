@echo off
set PYTHONPATH=%~dp0src;%PYTHONPATH%
python -m sniff.cli %*
