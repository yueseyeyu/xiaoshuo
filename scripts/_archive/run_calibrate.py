#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Wrapper to run calibrate_with_tier3.py and capture output"""
import sys, traceback, io

log = io.StringIO()
try:
    # Redirect stdout to log
    old_stdout = sys.stdout
    sys.stdout = log
    
    # Run the script
    exec(compile(open('scripts/calibrate_with_tier3.py', encoding='utf-8').read(), 'calibrate', 'exec'))
    
    sys.stdout = old_stdout
    output = log.getvalue()
    
    # Write to file
    with open('scripts/calib_result.txt', 'w', encoding='utf-8') as f:
        f.write(output)
    
    # Also print
    sys.stdout.write(output)
    
except Exception as e:
    sys.stdout = old_stdout
    error_msg = f"ERROR: {e}\n\n{traceback.format_exc()}"
    with open('scripts/calib_error.txt', 'w', encoding='utf-8') as f:
        f.write(error_msg)
    sys.stdout.write(error_msg)
