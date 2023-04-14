OneDrive Extractor
=============

Description

**Table of contents:**

[TOC]

Functionality notes
===================

Prerequisites
=============

For personal OneDrive, you only need to do OAuth authorization.
For Work or School account where SharePoint API is used, additionally to OAuth, you need to know the Tenant ID and site name.


Supported endpoints
===================

If you want to request new features, please submit your request to
[ideas.keboola.com](https://ideas.keboola.com/)

Configuration
=============

- **account_type**: Account Type
- **tenant_id**: Tenant ID. You can find the Tenant ID in the Azure Portal. After signing in, click on 'Azure Active Directory' in the left-hand menu. The Tenant ID can be found in the 'Tenant information' section on the 'Azure Active Directory' overview page.
- **site_name**: Site Name. You can find the site name in the url address when you visit your SharePoint or OneDrive for Business.
- **folder**: Folder (optional). Folder to search and download the files from.
- **mask**: Mask (optional). Examples: \*, report_\*.xlsx, \*.csv
- **last_modified_at**: Last Modified At (optional). Date from which data is downloaded. Either date in YYYY-MM-DD format or dateparser string i.e. 5 days ago, 1 month ago, yesterday, etc. You can also set this as last run, which will fetch data from the last run of the component.
- **custom_tag**: Custom Tag (optional). Adds custom tag to Keboola Storage for all downloaded files. Only one custom tag is supported.

Output
======

List of tables, foreign keys, schema.

Development
-----------

If required, change local data folder (the `CUSTOM_FOLDER` placeholder) path to
your custom path in the `docker-compose.yml` file:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    volumes:
      - ./:/code
      - ./CUSTOM_FOLDER:/data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clone this repository, init the workspace and run the component with following
command:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
git clone https://bitbucket.org/kds_consulting_team/kds-team.ex-onedrive/src/master/ kds-team.ex-onedrive
cd kds-team.ex-onedrive
docker-compose build
docker-compose run --rm dev
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the test suite and lint check using this command:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
docker-compose run --rm test
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Integration
===========

For information about deployment and integration with KBC, please refer to the
[deployment section of developers
documentation](https://developers.keboola.com/extend/component/deployment/)
