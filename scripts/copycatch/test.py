import io
import os
import sys
import json
import random
import logging
import argparse
import pandas as pd

from google.cloud import bigquery
from google.cloud.bigquery import ExtractJobConfig

from scripts import (
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
    START_DATE,
    END_DATE,
)
from scripts.gcp import (
    check_gcp_blob_exists,
    download_gcp_blob_to_stream,
    process_bigquery,
)
from scripts.copycatch.iterative import (
    CopyCatch,
    CopyCatchParams,
)


def get_stargazer_data_dagster(start_date: str, end_date: str):
    stars = pd.read_csv("data/fake_stars_complex_users.csv")
    fake_stars = stars[stars.fake_acct != "unknown"]
    actors, fake_actors = set(stars.actor), set(fake_stars.actor)
    real_actors = random.sample(list(actors - fake_actors), len(fake_actors))
    logging.info(
        "%d stars (%d fake) from %d actors (%d fake)",
        len(stars),
        len(fake_stars),
        len(actors),
        len(fake_actors),
    )

    client = bigquery.Client()
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    for actors, actor_type in zip([fake_actors, real_actors], ["fake", "real"]):
        output_file = f"test_dagster_stargazers_{actor_type}.json"
        if check_gcp_blob_exists(GCP_BUCKET, output_file):
            logging.info("Test data for %s actors already exists", actor_type)
            continue

        bigquery_task = {
            "interactive": True,
            "query_file": "scripts/copycatch/queries/stg_stargazers_by_names.sql",
            "output_table_id": f"test_dagster_stargazers_{actor_type}",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
                bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
                bigquery.ArrayQueryParameter("actors", "STRING", actors),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

        # Safe to export as a single file as the table is less than 1GB each
        extract_job = client.extract_table(
            source=dataset_ref.table(f"test_dagster_stargazers_{actor_type}"),
            destination_uris=f"gs://{GCP_BUCKET}/{output_file}",
            job_config=ExtractJobConfig(
                destination_format=(bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON)
            ),
        )
        extract_job.result()

        events = []
        stream = download_gcp_blob_to_stream(GCP_BUCKET, output_file, io.BytesIO())
        for line in stream.readlines():
            events.append(json.loads(line))
        events = pd.DataFrame(events)
        events.to_csv(f"data/copycatch_test_stargazers_{actor_type}.csv", index=False)
        logging.info("Generated test data for %s actors", actor_type)


def test_iterative_synthetic():
    copycatch_params = CopyCatchParams(
        delta_t=180 * 24 * 60 * 60,
        n=1,
        m=1,
        rho=0.5,
        beta=2,
    )

    for i in range(1, 4):
        logging.info("Running synthetic test %d...", i)
        syn = pd.read_csv(f"data/copycatch_test/synthetic{i}.csv")
        copycatch = CopyCatch.from_df(copycatch_params, syn)
        copycatch.run_all()

    logging.info("Running synthetic test 3 with m = 2...")
    copycatch_params.m = 2
    copycatch = CopyCatch.from_df(copycatch_params, syn)
    copycatch.run_all()

    logging.info("Running synthetic test 3 with delta_t = 400 days...")
    copycatch_params.delta_t = 400 * 24 * 60 * 60
    copycatch = CopyCatch.from_df(copycatch_params, syn)
    copycatch.run_all()

    logging.info("Running synthetic test 3 with m = 3...")
    copycatch_params.m = 3
    copycatch = CopyCatch.from_df(copycatch_params, syn)
    copycatch.run_all()


def test_iterative_one_repo(test_repo: str, actor_type: str):
    copycatch_params = CopyCatchParams(
        delta_t=180 * 24 * 60 * 60,
        n=20,
        m=4,
        rho=0.5,
        beta=2,
    )

    logging.info("Searching Dagster's %s stars for %s...", actor_type, test_repo)
    stargazers = pd.read_csv(f"data/copycatch_test/stargazers_{actor_type}.csv")
    actors = set(stargazers[stargazers.repo_name == test_repo].actor)
    stargazers = stargazers[stargazers.actor.isin(actors)]
    logging.info(
        "%d edges, %d repos, %d stargazers",
        len(stargazers),
        len(stargazers.repo_name.unique()),
        len(actors),
    )
    copycatch = CopyCatch.from_df(copycatch_params, stargazers)
    fake_users = set()

    users, _ = copycatch.run_once(
        copycatch.find_closest_repos(copycatch.repo2id[test_repo], copycatch.m)
    )
    fake_users.update(users)

    # for users, repos in copycatch.run_all(n_jobs=8):
    #    logging.info("Found %d user cluster among %s", len(users), repos)
    #    if test_repo in repos:
    #        fake_users.update(users)
    logging.info("Found %d/%d fake users", len(fake_users), len(actors))


def main():
    parser = argparse.ArgumentParser(description="Run CopyCatch tests")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
        default=False,
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate test data",
        default=False,
    )
    parser.add_argument(
        "--test-synthetic",
        action="store_true",
        help="Run CopyCatch tests on simple synthetic data",
        default=False,
    )
    parser.add_argument(
        "--test-real",
        action="store_true",
        help="Run CopyCatch tests on real data",
        default=False,
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO if not args.debug else logging.DEBUG,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    if args.generate:
        if not os.path.exists("data/copycatch_test/stargazers_fake.csv"):
            get_stargazer_data_dagster(start_date=START_DATE, end_date=END_DATE)
        else:
            logging.info("Test data already exists")

    if args.test_synthetic:
        test_iterative_synthetic()

    if args.test_real:
        test_iterative_one_repo("holochain/holochain-client-js", "fake")
        test_iterative_one_repo("Bitcoin-ABC/bitcoin-abc", "fake")
        test_iterative_one_repo("Bitcoin-ABC/bitcoin-abc", "real")
        test_iterative_one_repo("ant-design/ant-design", "fake")
        test_iterative_one_repo("Joystream/joystream", "fake")
        test_iterative_one_repo("subquery/subql", "fake")
        test_iterative_one_repo("subquery/subql", "real")

    logging.info("Done!")


if __name__ == "__main__":
    main()
