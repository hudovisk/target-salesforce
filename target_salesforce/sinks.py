"""Salesforce target sink class, which handles writing streams."""

from typing import Dict, List, Optional
from dataclasses import asdict


from singer_sdk.sinks import BatchSink
from simple_salesforce import Salesforce, bulk2, exceptions
from target_salesforce.session_credentials import parse_credentials, SalesforceAuth
from target_salesforce.utils.exceptions import InvalidStreamSchema, SalesforceApiError
from singer_sdk.plugin_base import PluginBase
from target_salesforce.utils.validation import ObjectField
from target_salesforce.utils.transformation import transform_record

from target_salesforce.utils.validation import validate_schema_field


class SalesforceSink(BatchSink):
    """Salesforce target sink class."""

    max_size = 5000
    valid_actions = ["insert", "update", "delete", "hard_delete", "upsert"]
    include_sdc_metadata_properties = False

    def __init__(
        self,
        target: PluginBase,
        stream_name: str,
        schema: Dict,
        key_properties: Optional[List[str]],
    ):
        super().__init__(target, stream_name, schema, key_properties)
        self.target = target
        self._sf_client = None
        self._batched_records: List[Dict]
        self._object_fields: Dict[str, ObjectField] = None
        self._validate_schema_against_object()

    @property
    def sf_client(self):
        if self._sf_client:
            return self._sf_client
        return self._new_session()

    @property
    def object_fields(self) -> Dict[str, ObjectField]:
        if self._object_fields:
            return self._object_fields
        object_fields = {}

        stream_object = getattr(self.sf_client, self.stream_name)
        for field in stream_object.describe().get("fields"):
            object_fields[field.get("name")] = ObjectField(
                field.get("type"),
                field.get("createable"),
                field.get("updateable"),
            )

        self._object_fields = object_fields
        return self._object_fields

    def _validate_schema_against_object(self):
        for field in self.schema.get("properties").items():
            try:
                validate_schema_field(
                    field, self.object_fields, self.config.get("action"), self.stream_name
                )
            except InvalidStreamSchema as e:
                raise InvalidStreamSchema(
                    f"The incomming schema is incompatable with your {self.stream_name} object"
                ) from e

    def _new_session(self):
        session_creds = SalesforceAuth.from_credentials(
            parse_credentials(self.target.config),
            domain=self.target.config["domain"],
        ).login()
        self._sf_client = Salesforce(**asdict(session_creds))
        return self._sf_client

    def start_batch(self, context: dict) -> None:
        self.logger.info(f"Starting new batch")
        self._batched_records = []

    def process_record(self, record: dict, context: dict) -> None:
        """Transform and batch record"""

        processed_record = transform_record(record, self.object_fields)

        self._batched_records.append(processed_record)

    def process_batch(self, context: dict) -> None:
        """Write out any prepped records and return once fully written."""

        sf_object: bulk2.SFBulk2Type = getattr(self.sf_client.bulk2, self.stream_name)

        results = self._process_batch_by_action(
            sf_object, self.config.get("action"), self._batched_records
        )

        self._validate_batch_result(
            sf_object, results, self.config.get("action")
        )

        # Refresh session to avoid timeouts.
        self._new_session()

    def _process_batch_by_action(
        self, sf_object: bulk2.SFBulk2Type, action, batched_data
    ):
        """Dispatch the batch to the matching Bulk 2.0 ingest method.

        Bulk 2.0 ingest methods take ``records=`` as a keyword argument and
        return one summary dict per chunk, not per-record results.
        """

        sf_object_action = getattr(sf_object, action)

        try:
            if action == "upsert":
                return sf_object_action(records=batched_data, external_id_field="Id")
            return sf_object_action(records=batched_data)
        except exceptions.SalesforceMalformedRequest as e:
            self.logger.error(
                f"Data in {action} {self.stream_name} batch does not conform to target SF {self.stream_name} Object"
            )
            raise

    def _validate_batch_result(
        self, sf_object: bulk2.SFBulk2Type, results: List[Dict], action
    ):
        total_processed = 0
        total_failed = 0
        total_records = 0

        for job in results:
            total_records += int(job.get("numberRecordsTotal", 0))
            total_processed += int(job.get("numberRecordsProcessed", 0))
            failed = int(job.get("numberRecordsFailed", 0))
            total_failed += failed
            if failed > 0:
                job_id = job.get("job_id")
                try:
                    failed_csv = sf_object.get_failed_records(job_id)
                    self.logger.error(
                        f"Failed records for {action} {self.stream_name} "
                        f"(job {job_id}):\n{failed_csv}"
                    )
                except Exception as exc:
                    self.logger.error(
                        f"Could not fetch failed records for job {job_id}: {exc}"
                    )

        successful = total_processed - total_failed
        self.logger.info(
            f"{action} {successful}/{total_records} to {self.stream_name}."
        )

        if total_failed > 0 and not self.config.get("allow_failures"):
            raise SalesforceApiError(
                f"{total_failed} error(s) in {action} batch commit to {self.stream_name}."
            )
