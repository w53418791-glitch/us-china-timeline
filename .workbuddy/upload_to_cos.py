#!/usr/bin/env python3
"""COS已弃用（浏览器下载问题），重定向到GitHub上传脚本"""
import os, subprocess, sys
subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'upload_to_github.py')])
