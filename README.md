![Silverlight Site Finder](./assets/pictures/Silverlight-Finder.png)

# Silverlight Site Finder

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)
![License](https://img.shields.io/badge/License-Project%20Use%20Only-lightgrey)

A desktop tool for identifying legacy Microsoft Silverlight applications and web pages.

</div>

## Overview

Silverlight Site Finder helps locate Silverlight-based applications by scanning individual URLs, crawling domains, and checking for commonly used Silverlight indicators such as:

- .xap file references
- application/x-silverlight MIME types
- Silverlight.js includes
- object/embed tags
- JavaScript patterns used by legacy Silverlight apps

Each result is assigned a confidence level and includes evidence collected during the scan.

## Features

- Scan a single URL or crawl a whole domain
- Search for likely Silverlight candidates using common discovery queries
- Rank findings by confidence level
- Inspect the evidence behind every result
- Export findings as JSON or CSV
- Open useful search dorks in a browser
- Generate XML for Microsoft Edge IE Mode compatibility

## Requirements

- Python 3.8 or newer
- Windows (the app uses `tkinter` for the desktop GUI)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python silverlight_finder.py
```

## Typical use cases

- Legacy application inventory
- Security assessments and architecture reviews
- Compatibility and modernization planning
- Discovery of old Silverlight dependencies in internal or external systems

## Important notes

Because some legacy systems still think Silverlight is the future, this tool is here to help you spot the dinosaurs before they bite back.

