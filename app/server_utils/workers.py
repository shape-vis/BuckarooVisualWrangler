"""
The server's worker threads - October 12, 2026

Building a node and drawing its plots is almost all SQL: Postgres does the work, and the Python thread that sent
the query waits for the answer. psycopg2 lets go of the GIL while it waits, so plain threads run that work truly in
parallel - every query runs in its own Postgres backend process, on its own core.

Two pools, so neither can starve the other:

    QUERY_POOL   independent queries - one column's profile, one drift measurement
    NODE_POOL    whole node builds - one staged candidate each

The rule that keeps them from deadlocking: only a request's thread or a node build waits on QUERY_POOL. A query task
never submits more work and never waits on anything, so every query the pool accepts runs to the end without needing
another worker. Nothing waits on NODE_POOL from inside it.

The connection pool in app/__init__.py is sized for both pools at full tilt, plus the requests the threaded dev
server is serving.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import partial

QUERY_WORKERS = 8
NODE_WORKERS = 4

QUERY_POOL = ThreadPoolExecutor(max_workers=QUERY_WORKERS, thread_name_prefix="query")
NODE_POOL = ThreadPoolExecutor(max_workers=NODE_WORKERS, thread_name_prefix="node-build")


def run_queries(work, items):
    """
    Run one independent query per item on QUERY_POOL, and wait for them all.

    :param work: a function of one item that runs its queries and returns a result. It must not submit to either
                 pool itself.
    :param items: what to run it on
    :return: the results, in the items' order. If any failed, the first failure is raised once all have finished.
    """
    tasks = []
    for item in items:
        tasks.append(partial(work, item))
    return run_all(tasks)


def run_all(tasks):
    """
    Run independent queries on QUERY_POOL, and wait for them all.

    :param tasks: functions of no arguments, each running its queries and returning a result. None may submit to
                  either pool itself.
    :return: the results, in the tasks' order. If any failed, the first failure is raised once all have finished.
    """
    futures = []
    for task in tasks:
        futures.append(QUERY_POOL.submit(task))

    results = []
    first_error = None
    for future in futures:
        try:
            results.append(future.result())
        except Exception as error:
            if first_error is None:
                first_error = error
            results.append(None)

    if first_error is not None:
        raise first_error
    return results
