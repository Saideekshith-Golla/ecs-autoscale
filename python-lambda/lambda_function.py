#!/usr/bin/env python

"""
Lambda function to autoscale ECS clusters.
"""

import datetime
import inspect
import logging
import os
import re
import sys

base_path = os.path.dirname(os.path.abspath(inspect.stack()[0][1]))
sys.path.append(os.path.join(base_path, "./packages/"))

import yaml
import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()
logger.setLevel(logging.INFO)

from autoscaling.ec2_instances import scale_ec2_instances
from autoscaling.services import gather_services


# Load cluster autoscaling definitions.
clusters_defs_path = os.path.join(
    base_path,
    "./clusters.yml"
)

with open(clusters_defs_path, "r") as f:
    raw = f.read()

# Replace env variables in the yaml defs.
for match, env_var in re.findall(r"(%\(([A-Za-z_]+)\))", raw):
    raw = raw.replace(match, os.environ[env_var])

cluster_defs = yaml.load(raw)


def lambda_handler(event, context):
    """
    Main function which is invoked by AWS Lambda.
    """
    logger.info("Got event {}".format(event))
    for cluster_name in cluster_defs["clusters"]:
        try:
            cluster_def = cluster_defs["clusters"][cluster_name]
            if not cluster_def["enabled"]:
                logger.warning(
                    "[Cluster: {}] Skipping since not enabled"\
                    .format(cluster_name)
                )
                continue

            # (1 / 4) Collect individual services in the cluster that will need to
            # be scaled.
            services = gather_services(cluster_name, cluster_def)
            logger.info(
                "[Cluster: {}] Found {:d} services that need to scale"\
                .format(cluster_name, len(services))
            )

            # (2 / 4) Increase the CPU and memory buffers according to the services
            # that need to scale.
            for service in services:
                cluster_def["cpu_buffer"] += service.cpu_increase
                cluster_def["cpu_buffer"] = max([cluster_def["cpu_buffer"], 0])
                cluster_def["mem_buffer"] += service.mem_increase
                cluster_def["mem_buffer"] = max([cluster_def["mem_buffer"], 0])

            # (3 / 4) Scale EC2 instances.
            res = scale_ec2_instances(cluster_name, cluster_def)
            if res == -1:
                # No instances in the cluster or something else went wrong.
                continue

            # (4 / 4) Scale services.
            for service in services:
                service.scale()
        except Exception as ex:
            logger.exception(ex)


if __name__ == "__main__":
    lambda_handler(1, 2)
