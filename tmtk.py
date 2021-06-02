#!/usr/bin/env python3
"""
Test kit for Tendermint testnet
"""

import argparse
import os
import os.path
import string
import sys
import re
import logging
import subprocess
import shlex
import time
import hashlib
from typing import OrderedDict as OrderedDictType, List, Dict, Set
from collections import namedtuple, OrderedDict
from copy import copy, deepcopy
import zipfile
import shutil
import pwd
import json
import datetime
import base64
import tempfile

import yaml
import colorlog
import requests
import toml
import pytz

logger = logging.getLogger("")

def main():
    parser = argparse.ArgumentParser(
        description="Test kit for Tendermint testnet",
    )
    parser.add_argument(
        "-c", "--config", 
        default="./tmtestplan.yaml",
        help="The path to the configuration file to use (default: ./tmtestplan.yaml)"
    )
    # parser.add_argument(
    #     "--aws-keypair-name",
    #     default=default_aws_keypair_name,
    #     help="The name of the AWS keypair you need to use to interact with AWS (defaults to your current username)",
    # )
    # parser.add_argument(
    #     "--ec2-private-key",
    #     default=default_ec2_private_key,
    #     help="The path to the private key that corresponds to your AWS keypair (default: ~/.ssh/ec2-user.pem)",
    # )
    parser.add_argument(
        "--fail-on-missing-envvars",
        action="store_true",
        default=False,
        help="Causes the script to fail entirely if an environment variable used in the config file is not set (default behaviour will just insert an empty value)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Increase output verbosity",
    )
    subparsers = parser.add_subparsers(
        required=True,
        dest="command",
        help="The tmtestnet command to execute",
    )

    # network
    parser_network = subparsers.add_parser(
        "network", 
        help="Network-related functionality",
    )
    subparsers_network = parser_network.add_subparsers(
        required=True,
        dest="subcommand",
        help="The network-related command to execute",
    )

    # network deploy
    parser_network_deploy = subparsers_network.add_parser(
        "deploy", 
        help="Deploy a network according to its configuration file",
    )
    parser_network_deploy.add_argument(
        "--keep-existing-tendermint-config",
        action="store_true",
        help="If this flag is specified and configuration is already present for a particular node group, it will not be overwritten/regenerated",
    )

    # network destroy
    parser_network_destroy = subparsers_network.add_parser(
        "destroy", 
        help="Destroy a deployed network",
    )
    parser_network_destroy.add_argument(
        "--keep-monitoring",
        action="store_true",
        help="If this flag is set, any deployed monitoring services will be preserved, while all other services will be destroyed",
    )

    # network start
    parser_network_start = subparsers_network.add_parser(
        "start", 
        help="Start one or more node(s) or node group(s)",
    )
    parser_network_start.add_argument(
        "node_or_group_ids",
        metavar="node_or_group_id",
        nargs="*",
        help="Zero or more node or group IDs of network node(s) to start. If this is not supplied, all nodes will be started."
    )
    parser_network_start.add_argument(
        "--no-fail-on-missing",
        default=False,
        action="store_true",
        help="By default, this command fails if a group/node reference has not yet been deployed. Specifying this flag will just skip that group/node instead.",
    )

    # network stop
    parser_network_stop = subparsers_network.add_parser(
        "stop", 
        help="Stop one or more node(s) or node group(s)",
    )
    parser_network_stop.add_argument(
        "node_or_group_ids",
        metavar="node_or_group_id",
        nargs="*",
        help="Zero or more node or group IDs of network node(s) to stop. If this is not supplied, all nodes will be stopped."
    )
    parser_network_stop.add_argument(
        "--no-fail-on-missing",
        default=False,
        action="store_true",
        help="By default, this command fails if a group/node reference has not yet been deployed. Specifying this flag will just skip that group/node instead.",
    )

    # network fetch_logs
    parser_network_fetch_logs = subparsers_network.add_parser(
        "fetch_logs",
        help="Fetch the logs for one or more node(s) or node group(s). " +
            "Note that this stops any running service instances on the target " +
            "nodes prior to fetching the logs, and then restarts those instances " +
            "that were running previously.",
    )
    parser_network_fetch_logs.add_argument(
        "output_path",
        help="Where to store all desired nodes' logs."
    )
    parser_network_fetch_logs.add_argument(
        "node_or_group_ids",
        metavar="node_or_group_id",
        nargs="*",
        help="Zero or more node or group IDs of network node(s). If this is not supplied, all nodes' logs will be fetched."
    )

    # network reset
    parser_network_reset = subparsers_network.add_parser(
        "reset",
        help="Reset the entire Tendermint network without redeploying VMs",
    )
    parser_network_reset.add_argument(
        "--truncate-logs",
        action="store_true",
        help="If set, the network reset operation will truncate the Tendermint logs prior to starting Tendermint",
    )

    # network info
    subparsers_network.add_parser(
        "info",
        help="Show information about a deployed network (e.g. hostnames and node IDs)",
    )

    # loadtest
    parser_loadtest = subparsers.add_parser(
        "loadtest", 
        help="Load testing-related functionality",
    )
    subparsers_loadtest = parser_loadtest.add_subparsers(
        required=True,
        dest="subcommand",
        help="The load testing-related sub-command to execute",
    )

    # loadtest start <id>
    parser_loadtest_start = subparsers_loadtest.add_parser("start", help="Start a specific load test")
    parser_loadtest_start.add_argument(
        "load_test_id", 
        help="The ID of the load test to start",
    )

    # loadtest stop <id>
    parser_loadtest_stop = subparsers_loadtest.add_parser(
        "stop", 
        help="Stop any currently running load tests",
    )
    parser_loadtest_stop.add_argument(
        "load_test_id", 
        help="The ID of the load test to stop",
    )

    # loadtest destroy
    subparsers_loadtest.add_parser(
        "destroy", 
        help="Stop any currently running load tests",
    )

    args = parser.parse_args()

    configure_logging(verbose=args.verbose)
    # Allow for interpolation of environment variables within YAML files
    configure_env_var_yaml_loading(fail_on_missing=args.fail_on_missing_envvars)

    kwargs = {
        # "aws_keypair_name": os.environ.get("AWS_KEYPAIR_NAME", getattr(args, "aws_keypair_name", default_aws_keypair_name)),
        # "ec2_private_key_path": os.environ.get("EC2_PRIVATE_KEY", getattr(args, "ec2_private_key", default_ec2_private_key)),
        "keep_existing_tendermint_config": getattr(args, "keep_existing_tendermint_config", False),
        "output_path": getattr(args, "output_path", None),
        "node_or_group_ids": getattr(args, "node_or_group_ids", []),
        "fail_on_missing": not getattr(args, "no_fail_on_missing", False),
        "load_test_id": getattr(args, "load_test_id", None),
        "keep_monitoring": getattr(args, "keep_monitoring", False),
        "truncate_logs": getattr(args, "truncate_logs", False),
    }
    sys.exit(tmtest(args.config, args.command, args.subcommand, **kwargs))


# -----------------------------------------------------------------------------
#
#   Constants
#
# -----------------------------------------------------------------------------

ENV_VAR_MATCHERS = [
    re.compile(r"\$\{(?P<env_var_name>[^}^{]+)\}"),
    re.compile(r"\$(?P<env_var_name>[A-Za-z0-9_]+)"),
]

TMTEST_HOME = os.environ.get("TMTEST_HOME", "~/.tmtestkit")

# -----------------------------------------------------------------------------
#
#   Core functionality
#
# -----------------------------------------------------------------------------

def tmtest(cfg_file, command, subcommand, **kwargs) -> int:
    """The primary programmatic interface to the tm-test tool. Allows the
    tool to be imported from other Python code. Returns the intended exit code
    from execution."""
    
    try:
        cfg = load_test_config(cfg_file)
    except Exception as e:
        logger.error("Failed to load configuration from file: %s", cfg_file)
        logger.exception(e)
        return 1

    fn = None

    if command == "network":
        if subcommand == "deploy":
            fn = network_deploy
    #     elif subcommand == "destroy":
    #         fn = network_destroy
    #     elif subcommand == "start":
    #         fn = network_start
    #     elif subcommand == "stop":
    #         fn = network_stop
    #     elif subcommand == "fetch_logs":
    #         fn = network_fetch_logs
    #     elif subcommand == "reset":
    #         fn = network_reset
    #     elif subcommand == "info":
    #         fn = network_info
    # elif command == "loadtest":
    #     if subcommand == "start":
    #         fn = loadtest_start
    #     elif subcommand == "stop":
    #         fn = loadtest_stop
    #     elif subcommand == "destroy":
    #         fn = loadtest_destroy

    if fn is None:
        logger.error("Command/sub-command not yet supported: %s %s", command, subcommand)
        return 1
    
    try:
        fn(cfg, **kwargs)
    except Exception as e:
        logger.error("Failed to execute \"%s %s\" for configuration file: %s", command, subcommand, cfg_file)
        logger.exception(e)
        return 1
    
    return 0
            

def load_test_config(filename: str) -> TestConfig:
    """Loads the configuration from the given file. Throws an exception if any
    validation fails. On success, returns the configuration."""

    # resolve the tmtest home folder path
    tmtest_home = os.path.expanduser(TMTEST_HOME)
    ensure_path_exists(tmtest_home)

    with open(filename, "rt") as f:
        cfg_dict = yaml.safe_load(f)
    
    if "id" not in cfg_dict:
        raise Exception("Missing required \"id\" parameter in configuration file")

    config_base_path = os.path.dirname(os.path.abspath(filename))
    return TestConfig(
        id=cfg_dict["id"],
        # monitoring=load_monitoring_config(cfg_dict.get("monitoring", dict())),
        # abci=load_abci_configs(cfg_dict.get("abci", dict()), config_base_path),
        # node_groups=load_node_groups_config(cfg_dict.get("node_groups", []), config_base_path, abci_config),
        # load_tests=load_load_tests_config(cfg_dict.get("load_tests", [])),
        home=tmtest_home,
    )


def configure_env_var_yaml_loading(fail_on_missing=False):
    for matcher in ENV_VAR_MATCHERS:
        yaml.add_implicit_resolver("!envvar", matcher, None, yaml.SafeLoader)
    yaml.add_constructor("!envvar", make_envvar_constructor(fail_on_missing=fail_on_missing), yaml.SafeLoader)

def make_envvar_constructor(fail_on_missing=False):
    def envvar_constructor(loader, node):
        """From https://stackoverflow.com/a/52412796/1156132"""
        value = node.value
        for matcher in ENV_VAR_MATCHERS:
            match = matcher.match(value)
            if match is not None:
                env_var_name = match.group("env_var_name")
                logger.debug("Parsed environment variable: %s", env_var_name)
                if fail_on_missing and env_var_name not in os.environ:
                    raise Exception("Missing environment variable during configuration file parsing: %s" % env_var_name)
                return os.environ.get(env_var_name, "") + value[match.end():]
        raise Exception("Internal error: environment variable matching algorithm failed")
    return envvar_constructor

def configure_logging(verbose=False):
    """Supercharge our logger."""
    handler = colorlog.StreamHandler()
    handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s\t%(levelname)s\t%(message)s",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "bold_yellow",
                "ERROR": "bold_red",
                "CRITICAL": "bold_red",
            }
        ),
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

def ensure_path_exists(path):
    if not os.path.isdir(path):
        os.makedirs(path, mode=0o755, exist_ok=True)
        logger.debug("Created folder: %s", path)

# def get_current_user() -> str:
#     return pwd.getpwuid(os.getuid())[0]

# -----------------------------------------------------------------------------
#
#   Configuration
#
# -----------------------------------------------------------------------------

TestConfig = namedtuple("TestConfig",
    ["id", "monitoring", "abci", "node_groups", "load_tests", "home", "tendermint_binaries"],
    defaults=[None, None, dict(), OrderedDict(), OrderedDict(), TMTEST_HOME, dict()],
)


if __name__ == "__main__":
    main()