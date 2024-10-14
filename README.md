OneDrive Data Source
=============

This connector downloads files from [Microsoft OneDrive](https://www.microsoft.com/en-us/microsoft-365/onedrive/online-cloud-storage) and stores them in your project.

The Microsoft OneDrive cloud storage integrates the [Office365](https://www.office.com/) and [SharePoint](https://www.microsoft.com/en-us/microsoft-365/sharepoint/collaboration) sites. It also supports SharePoint's document libraries. This connector lets you access all your files in your personal or business account.

With the flexibility of file path masks, you can now download multiple files within a single configuration. Additionally, you can selectively download only the files that have been updated.

**Table of contents:**

[TOC]

Prerequisites
=============

OAuth authorization is required for personal OneDrive, while for OneDrive for business, you need to know the Tenant ID in addition to OAuth. If you want to use Sharepoint, you also need to provide the site name.

#### Refresh Token

The refresh token is used to obtain a new access token. The refresh token is stored in the state file and is used for runs of the writer ROW! A problem with no valid refresh token can appear if new rows are added after the main OAuth refresh token expiration time.


Supported Features
===================

If you want to request new features, please submit your request to
[ideas.keboola.com](https://ideas.keboola.com/).

Configuration
=============

- **account_type**: Account type - This field is only used in GUI to display relevant fields for different account types.
- **tenant_id**: Tenant ID is needed for OneDrive for Business and SharePoint. You can find the Tenant ID in the Azure Portal. After signing in, click 'Azure Active Directory' in the left-hand menu. The Tenant ID can be found in the 'Tenant information' section on the 'Azure Active Directory' overview page.
- **site_url**: The site URL is only needed for SharePoint. You can find the site name in the URL address when you visit your SharePoint online.
- **library_name**: Library name (optional) is used to select the Document Library from which you want to download files. If you do not wish to download files from the Document Library, leave this field empty.
- **file_path**: Path to the file/s you want to download from the selected service. Supports wildcards.
     - Examples: 
       - \*.csv - Downloads all available CSV files.
       - /reports/\*.csv - Downloads all available CSV files from the reports folder and its subfolders.
       - db_exports/report_\*.xlsx - Downloads all .xlsx files that are named report_\* (\* is wildcard) from the db_exports folder and its subfolders. 
       - db_exports/2022_\*/\*.csv - Downloads all CSV files from folders matching db_exports/2022_\* (\* is wildcard). 
- **new_files_only**: New files only (optional). If set to true, the component will use the timestamp of the freshest file downloaded last run to download only newer files. The LastModifiedAt value from GraphAPI is used.
- **custom_tag**: Custom tag (optional). Adds a custom tag to Keboola Storage for all downloaded files. Only one custom tag is supported.
- **permanent**: Permanent files (optional). If set to true, downloaded files will be stored in Keboola Storage permanently. Otherwise, they will be deleted after 14 days.

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

If required, change the local data folder (the `CUSTOM_FOLDER` placeholder) path to
your custom path in the `docker-compose.yml` file:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    volumes:
      - ./:/code
      - ./CUSTOM_FOLDER:/data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clone this repository, init the workspace and run the component with the following
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

For information about deployment and integration with Keboola, please refer to the
[deployment section of our developer
documentation](https://developers.keboola.com/extend/component/deployment/).
