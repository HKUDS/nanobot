import pickle
from datetime import datetime, timezone

from apscheduler.job import Job
from apscheduler.jobstores.base import BaseJobStore, ConflictingIdError, JobLookupError
from apscheduler.util import (
    datetime_to_utc_timestamp,
    maybe_ref,
    utc_timestamp_to_datetime,
)

try:
    from etcd3 import Etcd3Client
except ImportError as exc:  # pragma: nocover
    raise ImportError("EtcdJobStore requires etcd3 be installed") from exc


class EtcdJobStore(BaseJobStore):
    """
    Stores jobs in a etcd. Any leftover keyword arguments are directly passed to
    etcd3's `etcd3.client
    <https://python-etcd3.readthedocs.io/en/latest/readme.html>`_.

    Plugin alias: ``etcd``

    :param str path: path to store jobs in
    :param client: a :class:`~etcd3.client.etcd3` instance to use instead of
        providing connection arguments
    :param int pickle_protocol: pickle protocol level to use (for serialization), defaults to the
        highest available
    """

    def __init__(
        self,
        path="/apscheduler",
        client=None,
        close_connection_on_exit=False,
        pickle_protocol=pickle.DEFAULT_PROTOCOL,
        **connect_args,
    ):
        super().__init__()
        self.pickle_protocol = pickle_protocol
        self.close_connection_on_exit = close_connection_on_exit

        if not path:
            raise ValueError('The "path" parameter must not be empty')

        self.path = path

        if client:
            self.client = maybe_ref(client)
        else:
            self.client = Etcd3Client(**connect_args)

    def lookup_job(self, job_id):
        node_path = self.path + "/" + str(job_id)
        try:
            content, _ = self.client.get(node_path)
            content = pickle.loads(content)
            job = self._reconstitute_job(content["job_state"])
            return job
        except BaseException:
            return None

    def get_due_jobs(self, now):
        timestamp = datetime_to_utc_timestamp(now)
        jobs = [
            job_record["job"]
            for job_record in self._get_jobs()
            if job_record["next_run_time"] is not None
            and job_record["next_run_time"] <= timestamp
        ]
        return jobs

    def get_next_run_time(self):
        next_runs = [
            job_record["next_run_time"]
            for job_record in self._get_jobs()
            if job_record["next_run_time"] is not None
        ]
        return utc_timestamp_to_datetime(min(next_runs)) if len(next_runs) > 0 else None

    def get_all_jobs(self):
        jobs = [job_record["job"] for job_record in self._get_jobs()]
        self._fix_paused_jobs_sorting(jobs)
        return jobs

    def add_job(self, job):
        node_path = self.path + "/" + str(job.id)
        value = {
            "next_run_time": datetime_to_utc_timestamp(job.next_run_time),
            "job_state": job.__getstate__(),
        }
        data = pickle.dumps(value, self.pickle_protocol)
        status = self.client.put_if_not_exists(node_path, value=data)
        if not status:
            raise ConflictingIdError(job.id)

    def update_job(self, job):
        node_path = self.path + "/" + str(job.id)
        changes = {
            "next_run_time": datetime_to_utc_timestamp(job.next_run_time),
            "job_state": job.__getstate__(),
        }
        data = pickle.dumps(changes, self.pickle_protocol)
        status, _ = self.client.transaction(
            compare=[self.client.transactions.version(node_path) > 0],
            success=[self.client.transactions.put(node_path, value=data)],
            failure=[],
        )
        if not status:
            raise JobLookupError(job.id)

    def remove_job(self, job_id):
        node_path = self.path + "/" + str(job_id)
        status, _ = self.client.transaction(
            compare=[self.client.transactions.version(node_path) > 0],
            success=[self.client.transactions.delete(node_path)],
            failure=[],
        )
        if not status:
            raise JobLookupError(job_id)

    def remove_all_jobs(self):
        self.client.delete_prefix(self.path)

    def shutdown(self):
        self.client.close()

    def _reconstitute_job(self, job_state):
        job_state = job_state
        job = Job.__new__(Job)
        job.__setstate__(job_state)
        job._scheduler = self._scheduler
        job._jobstore_alias = self._alias
        return job

    def _get_jobs(self):
        jobs = []
        failed_job_ids = []
        all_ids = list(self.client.get_prefix(self.path))

        for doc, _ in all_ids:
            try:
                content = pickle.loads(doc)
                job_record = {
                    "next_run_time": content["next_run_time"],
                    "job": self._reconstitute_job(content["job_state"]),
                }
                jobs.append(job_record)
            except BaseException:
                content = pickle.loads(doc)
                failed_id = content["job_state"]["id"]
                failed_job_ids.append(failed_id)
                self._logger.exception(
                    'Unable to restore job "%s" -- removing it', failed_id
                )

        if failed_job_ids:
            for failed_id in failed_job_ids:
                self.remove_job(failed_id)
        paused_sort_key = datetime(9999, 12, 31, tzinfo=timezone.utc)
        return sorted(
            jobs,
            key=lambda job_record: job_record["job"].next_run_time or paused_sort_key,
        )

    def __repr__(self):
        self._logger.exception("<%s (client=%s)>", self.__class__.__name__, self.client)
        return f"<{self.__class__.__name__} (client={self.client})>"
