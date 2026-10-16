'Helpers for jobs in the queue (ir.queue) - protection against starting a background job twice'
import datetime

from trytond.pool import Pool
from trytond.transaction import without_check_access

# A job taken by a worker longer ago than this without being finished is
# considered failed (a retry is queued as a new job) and blocks nothing
RUNNING_MINUTES = 60


def queued_ids(model, method):
    """Ids of the records of 'model' waiting in the queue for 'method': jobs
    not taken by a worker yet or taken within the last RUNNING_MINUTES and
    not finished - a job started again is not queued twice for them"""
    Queue = Pool().get('ir.queue')
    since = datetime.datetime.now() - datetime.timedelta(
        minutes=RUNNING_MINUTES)
    ids = set()
    with without_check_access():
        tasks = Queue.search([
                ('finished_at', '=', None),
                ['OR',
                    ('dequeued_at', '=', None),
                    ('dequeued_at', '>', since),
                    ],
                ])
    for task in tasks:
        data = task.data or {}
        if data.get('model') == model and data.get('method') == method:
            instances = data.get('instances')
            ids.update(instances if isinstance(instances, (list, tuple))
                else [instances])
    return ids
