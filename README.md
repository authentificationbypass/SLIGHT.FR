![Silverlight Site Finder](./assets/pictures/Silverlight-Finder.png)

# Silverlight Finder

A Python desktop tool for detecting legacy Microsoft Silverlight web applications.

## What it does

The tool helps identify Silverlight-based pages and applications by scanning single URLs, crawling a domain, or searching for known Silverlight indicators such as:

- .xap file references
- application/x-silverlight MIME types
- Silverlight.js includes
- object and embed tags
- JavaScript patterns used by Silverlight apps

It then rates the result by confidence and shows the relevant evidence for each finding.

## Features

- Scan single URLs
- Crawl a complete domain
- Search for likely Silverlight candidates using common discovery queries
- Highlight results by confidence level
- Inspect detailed indicators per match
- Export results as JSON or CSV
- Open common web-search dorks directly in a browser
- Generate XML for Edge IE Mode compatibility settings

## Requirements

- Python 3.8 or newer
- Windows, because the tool uses tkinter for the desktop GUI

## Install dependencies:

pip install -r requirements.txt

## Run

python silverlight_finder.py

## Notes

This project is intended for legitimate security assessments, IT audits, and compatibility work on systems you own or are authorized to test.

## Disclaimer

Use only in environments where you have permission to scan and analyze the target systems.