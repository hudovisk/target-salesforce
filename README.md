# target-salesforce

`target-salesforce` is a Singer target for Salesforce.

Build with the [Meltano Target SDK](https://sdk.meltano.com).

## Capabilities

* `about`
* `stream-maps`
* `schema-flattening`

## Configuration

### Accepted Config Options

You must authenticate with one of:

- **JWT bearer** (`jwt_client_id`, `jwt_username`, `jwt_private_key`) — recommended for unattended/server-to-server use, since it relies on a keypair rather than expiring passwords or revocable refresh tokens.
- **OAuth refresh-token** (`client_id`, `client_secret`, `refresh_token`).
- **Username/password** (`username`, `password`, `security_token`).

When more than one set is provided, the target picks in this order: JWT → OAuth → username/password.

| Setting             | Required | Default | Description |
|:--------------------|:--------:|:-------:|:------------|
| jwt_client_id       | False     | None    | JWT bearer: Connected/External Client App consumer key (iss claim) |
| jwt_username        | False     | None    | JWT bearer: Salesforce username to impersonate (sub claim). User must be pre-authorized for the app |
| jwt_private_key     | False     | None    | JWT bearer: RSA private key (PEM) matching the cert uploaded to the app |
| client_id           | False     | None    | OAuth client_id  |
| client_secret       | False     | None    | OAuth client_secret |
| refresh_token       | False     | None    | OAuth refresh_token |
| username            | False     | None    | User/password username |
| password            | False     | None    | User/password password |
| security_token      | False     | None    | User/password generated security token. Reset under your Account Settings |
| domain              | False     | login   | Your Salesforce instance domain. Use 'login' (default) or 'test' (sandbox), or Salesforce My domain. |
| action              | False     | update  | How to handle incomming records by default (insert/update/upsert/delete/hard_delete) |
| allow_failures      | False     | False   | Allows the target to continue persisting if a record fails to commit |

A full list of supported settings and capabilities for this
target is available by running:

```bash
target-salesforce --about
```

### Source Authentication and Authorization

- For Oauth, you must create a connected app. See details from the [Salesforce documentation](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_understanding_web_server_oauth_flow.htm).
- For JWT bearer, create a Connected/External Client App with the "Use digital signatures" option, upload an X.509 cert whose private key you control, pre-authorize the user (via profile or permission set), and ensure the user has consented to the app at least once (via the browser OAuth flow). See [Salesforce's JWT bearer flow docs](https://help.salesforce.com/s/articleView?id=xcloud.remoteaccess_oauth_jwt_flow.htm).

## Usage

Failure to ensure the following may result in incosistent results.
1. Incoming records must conform to your salesforce objects. Field Names (Case Sensitive) are validated by the target, but data types are not.
2. Stream name should match the target Object (ex. Account).
3. Insert records should not contain `Id` or any fields that are not createable.
4. Update records must contain `Id` or any fields that are not updateable.
5. Upsert records must contain `Id` and all fields must be createable and updateable.
6. Delete/hard_delete records should only contain `Id`

### General Workflow
Here's a possible workflow on how to best use this tap in an Operational Analytics use case.
1. tap-salesforce -> target-[DB]
2. Transform/enrich data with dbt resulting in a clean table/view that matches the format of the Salesforce object.
3. tap-[DB] -> target-salesforce
   - Consider using [inline stream maps](https://sdk.meltano.com/en/latest/stream_maps.html#customized-stream-map-behaviors) if you need to rename fields to match the SF Object

### Bulk API version

This target writes through Salesforce's **Bulk API 2.0** (`/services/data/vXX.0/jobs/ingest`). The earlier `1.x` versions of this target used Bulk API 1.0 via `simple_salesforce.bulk`, which authenticates with an `X-SFDC-Session` SOAP-style session id. That made it incompatible with OAuth2 JWT Bearer auth (JWT-issued access tokens are not valid SOAP session ids and every job fails with `InvalidSessionId`). Bulk 2.0 uses standard `Authorization: Bearer`, so it works with all three credential types (JWT, OAuth refresh-token, username/password).

Per-record results are not returned inline by Bulk 2.0; when a job has failures the target fetches the failed-records CSV (`sf__Id`, `sf__Error`, plus the original fields) via `simple_salesforce.bulk2.SFBulk2Type.get_failed_records()` and logs it.

### Troubleshooting
You can inspect the result of bulk API load jobs via the following URL:
[DOMAIN].lightning.force.com/lightning/setup/AsyncApiJobStatus/home

### Initialize your Development Environment

```bash
pipx install poetry
poetry install
```

### Executing the Target Directly
The following will insert an Account record from `input_example.jsonl` into your Salesforce instance. In your config, set `action=insert`.

```bash
target-salesforce --version
target-salesforce --help
cat input_example.jsonl | target-salesforce --config .secrets/config.json
```

### Create and Run Tests

Create tests within the `target_salesforce/tests` subfolder and
  then run:

```bash
poetry run pytest
```

You can also test the `target-salesforce` CLI interface directly using `poetry run`:

```bash
poetry run target-salesforce --help
```

### Testing with [Meltano](https://meltano.com/)

Your project comes with a custom `meltano.yml` project file already created. Open the `meltano.yml` and follow any _"TODO"_ items listed in
the file.

Next, install Meltano (if you haven't already) and any needed plugins:

```bash
# Install meltano
pipx install meltano
# Initialize meltano within this directory
cd target-salesforce
meltano install
```

Now you can test and orchestrate using Meltano:

```bash
# Test invocation:
meltano invoke target-salesforce --version
# OR run a test `elt` pipeline with the Carbon Intensity sample tap:
meltano elt tap-carbon-intensity target-salesforce
```

### SDK Dev Guide

See the [dev guide](https://sdk.meltano.com/en/latest/dev_guide.html) for more instructions on how to use the Meltano SDK to
develop your own Singer taps and targets.
