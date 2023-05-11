OneDrive Extractor
=============

Description

**Table of contents:**

[TOC]

Functionality notes
===================

Prerequisites
=============

OAuth authorization is required for personal OneDrive, while for OneDriveForBusiness, you need to know the Tenant ID in addition to OAuth. If you want to use Sharepoint, you will also need to provide the site name.

Supported features
===================

If you want to request new features, please submit your request to
[ideas.keboola.com](https://ideas.keboola.com/)

Configuration
=============

- **account_type**: Account Type - This field is only used in GUI to display relevant fields for different Account types.
- **tenant_id**: Tenant ID is needed for OneDrive for Business and SharePoint. You can find the Tenant ID in the Azure Portal. After signing in, click on 'Azure Active Directory' in the left-hand menu. The Tenant ID can be found in the 'Tenant information' section on the 'Azure Active Directory' overview page.
- **site_url**: Site URL is only needed for SharePoint. You can find the site name in the url address when you visit your SharePoint online.
- **library_name**: Library name (optional) is used to select Document Library from which you want to download files from. If you do not wish to download files from Document Library, leave this field empty.
- **file_path**: Path to file/s you want to download from selected service. Supports wildcards.
     - Examples: 
       - \*.csv - Downloads all available csv files.
       - /reports/\*.csv - Downloads all available csv files from reports folder and it's subfolders.
       - db_exports/report_\*.xlsx - Downloads all .xlsx files that are named like report_\* (\* is wildcard) from db_exports folder and it's subfolders. 
       - db_exports/2022_\*/\*.csv - Downloads all csv files from folders matching db_exports/2022_\* (\* is wildcard) 
- **new_files_only**: New Files Only (optional). If set to true, the component will use timestamp of the freshest file downloaded last run to download only newer files. LastModifiedAt value from GraphAPI is used.
- **custom_tag**: Custom Tag (optional). Adds custom tag to Keboola Storage for all downloaded files. Only one custom tag is supported.
- **permanent**: Permanent Files (optional). If set to true, downloaded files will be stored as permanent in Keboola storage. Otherwise, they will be deleted after 14 days.

Example Configuration
======

```json
{
   "account":{
      "tenant_id":"xxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "account_type":"onedrive_for_business"
   },
   "settings":{
      "file_path":"/extractor-test/subfolder/*.png",
      "new_files_only":false
   },
   "destination":{
      "custom_tag":"odb_test",
      "permanent": false
   }
}
```

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
