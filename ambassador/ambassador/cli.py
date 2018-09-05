# Copyright 2018 Datawire. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License

from typing import List, Optional

import sys

import json
import logging
import os
# import time
import traceback
# import uuid
import yaml

import clize
from clize import Parameter

from .config import Config, ACResource
from .ir import IR
from .envoy import V1Config

from .utils import RichStatus

from .VERSION import Version

__version__ = Version

logging.basicConfig(
    level=logging.DEBUG, # if appDebug else logging.INFO,
    format="%%(asctime)s ambassador %s %%(levelname)s: %%(message)s" % __version__,
    datefmt="%Y-%m-%d %H:%M:%S"
)

# logging.getLogger("datawire.scout").setLevel(logging.DEBUG)
logger = logging.getLogger("ambassador")
logger.setLevel(logging.DEBUG)

def handle_exception(what, e, **kwargs):
    tb = "\n".join(traceback.format_exception(*sys.exc_info()))

    # if Config.scout:
    #     result = Config.scout_report(action=what, mode="cli", exception=str(e), traceback=tb,
    #                                  runtime=Config.runtime, **kwargs)
    #
    #     logger.debug("Scout %s, result: %s" %
    #                  ("disabled" if Config.scout.disabled else "enabled", result))

    logger.error("%s: %s\n%s" % (what, e, tb))

    show_notices()

def show_notices(printer=logger.log):
    # if Config.scout_notices:
    #     for notice in Config.scout_notices:
    #         try:
    #             if isinstance(notice, str):
    #                 printer(logging.WARNING, notice)
    #             else:
    #                 lvl = notice['level'].upper()
    #                 msg = notice['message']
    #
    #                 if isinstance(lvl, str):
    #                     lvl = getattr(logging, lvl, logging.INFO)
    #
    #                 printer(lvl, msg)
    #         except KeyError:
    #             printer(logging.WARNING, json.dumps(notice))
    print("CANNOT SHOW NOTICES RIGHT NOW")

def stdout_printer(lvl, msg):
    print("%s: %s" % (logging.getLevelName(lvl), msg))

def version():
    """
    Show Ambassador's version
    """

    print("Ambassador %s" % __version__)

    # if Config.scout:
    #     Config.scout_report(action="version", mode="cli")
    #     show_notices(printer=stdout_printer)

def showid():
    """
    Show Ambassador's installation ID
    """

    # if Config.scout:
    #     print("%s" % Config.scout.install_id)
    #
    #     Config.scout_report(action="showid", mode="cli")
    #
    #     show_notices(printer=stdout_printer)
    # else:
    #     print("unknown")
    print("CANNOT SHOW ID RIGHT NOW")

class ResourceFetcher:
    def __init__(self, config_dir_path: str, k8s: bool=False) -> None:
        self.resources: List[ACResource] = []

        for filename in os.listdir(config_dir_path):
            filepath = os.path.join(config_dir_path, filename)

            if not os.path.isfile(filepath):
                continue

            self.filename: Optional[str] = filename
            self.filepath: Optional[str] = filepath
            self.ocount: int = 1

            logging.debug("init filename %s ocount %d" % (self.filename, self.ocount))

            serialization = open(filepath, "r").read()

            self.load_yaml(serialization, k8s=k8s)

            logging.debug("parsed filename %s ocount %d" % (self.filename, self.ocount))

            self.filename = None
            self.filepath = None
            self.ocount = 0

    def load_yaml(self, serialization: str, rkey: Optional[str]=None, k8s: bool=False) -> None:
        objects = list(yaml.safe_load_all(serialization))

        for obj in objects:
            if k8s:
                self.extract_k8s(serialization, obj)
            else:
                if not rkey:
                    rkey = "%s.%d" % (self.filename, self.ocount)

                r = ACResource.from_dict(rkey, rkey, serialization, obj)

                self.resources.append(r)

            self.ocount += 1

    def extract_k8s(self, serialization: str, obj: dict) -> None:
        kind = obj.get('kind', None)

        if kind != "Service":
            logger.debug("%s.%s: ignoring K8s %s object" % (self.filepath, self.ocount, kind))
            return

        metadata = obj.get('metadata', None)

        if not metadata:
            logger.debug("%s.%s: ignoring unannotated K8s %s" % (self.filepath, self.ocount, kind))
            return

        # Use metadata to build a unique resource identifier
        resource_name = metadata.get('name')

        # This should never happen as the name field is required in metadata for Service
        if not resource_name:
            logger.debug("%s.%s: ignoring unnamed K8s %s" % (self.filepath, self.ocount, kind))
            return

        resource_namespace = metadata.get('namespace', 'default')

        # This resource identifier is useful for log output since filenames can be duplicated (multiple subdirectories)
        resource_identifier = '{name}.{namespace}'.format(namespace=resource_namespace, name=resource_name)

        annotations = metadata.get('annotations', None)

        if annotations:
            annotations = annotations.get('getambassador.io/config', None)

        # self.logger.debug("annotations %s" % annotations)

        if not annotations:
            logger.debug("%s.%s: ignoring K8s %s without Ambassador annotation" % (self.filepath, self.ocount, kind))
            return

        self.filename += ":annotation"
        self.load_yaml(annotations, rkey=resource_identifier)

    def __iter__(self):
        return self.resources.__iter__()

def fetch_resources(config_dir_path: str, k8s=False):
    fetcher = ResourceFetcher(config_dir_path, k8s=k8s)
    return fetcher.__iter__()

def dump(config_dir_path:Parameter.REQUIRED, *,
         k8s=False, aconf=False, ir=False, v1=False):
    """
    Dump various forms of an Ambassador configuration for debugging

    Use --aconf, --ir, and --envoy to control what gets dumped. If none are requested, the IR
    will be dumped.

    :param config_dir_path: Configuration directory to scan for Ambassador YAML files
    :param k8s: If set, assume configuration files are annotated K8s manifests
    :param aconf: If set, dump the Ambassador config
    :param ir: If set, dump the IR
    :param v1: If set, dump the Envoy V1 config
    """

    if not (aconf or ir or v1):
        ir = True

    dump_aconf = aconf
    dump_ir = ir
    dump_v1 = v1

    try:
        resources = fetch_resources(config_dir_path, k8s=k8s)
        aconf = Config()
        aconf.load_all(resources)

        if dump_aconf:
            json.dump(aconf.as_dict(), sys.stdout, sort_keys=True, indent=4)
            sys.stdout.write("\n")

        ir = IR(aconf)

        if dump_ir:
            json.dump(ir.as_dict(), sys.stdout, sort_keys=True, indent=4)
            sys.stdout.write("\n")

        if dump_v1:
            v1config = V1Config(ir)
            json.dump(v1config.as_dict(), sys.stdout, sort_keys=True, indent=4)
            sys.stdout.write("\n")

    except Exception as e:
        handle_exception("EXCEPTION from dump", e,
                         config_dir_path=config_dir_path)

        # This is fatal.
        sys.exit(1)

def validate(config_dir_path:Parameter.REQUIRED, *, k8s=False):
    """
    Validate an Ambassador configuration

    :param config_dir_path: Configuration directory to scan for Ambassador YAML files
    :param k8s: If set, assume configuration files are annotated K8s manifests
    """
    config(config_dir_path, os.devnull, k8s=k8s, exit_on_error=True)

def config(config_dir_path:Parameter.REQUIRED, output_json_path:Parameter.REQUIRED, *,
           check=False, k8s=False, ir=None, aconf=None, exit_on_error=False):
    """
    Generate an Envoy configuration

    :param config_dir_path: Configuration directory to scan for Ambassador YAML files
    :param output_json_path: Path to output envoy.json
    :param check: If set, generate configuration only if it doesn't already exist
    :param k8s: If set, assume configuration files are annotated K8s manifests
    :param exit_on_error: If set, will exit with status 1 on any configuration error
    :param ir: Pathname to which to dump the IR (not dumped if not present)
    :param aconf: Pathname to which to dump the aconf (not dumped if not present)
    """

    try:
        logger.debug("CHECK MODE  %s" % check)
        logger.debug("CONFIG DIR  %s" % config_dir_path)
        logger.debug("OUTPUT PATH %s" % output_json_path)

        dump_aconf: Optional[str] = aconf
        dump_ir: Optional[str] = ir

        # Bypass the existence check...
        output_exists = False

        if check:
            # ...oh no wait, they explicitly asked for the existence check!
            # Assume that the file exists (ie, we'll do nothing) unless we
            # determine otherwise.
            output_exists = True

            try:
                x = json.loads(open(output_json_path, "r").read())
            except FileNotFoundError:
                logger.debug("output file does not exist")
                output_exists = False
            except OSError:
                logger.warning("output file is not sane?")
                output_exists = False
            except json.decoder.JSONDecodeError:
                logger.warning("output file is not valid JSON")
                output_exists = False

            logger.info("Output file %s" % ("exists" if output_exists else "does not exist"))

        rc = RichStatus.fromError("impossible error")

        if not output_exists:
            # Either we didn't need to check, or the check didn't turn up
            # a valid config. Regenerate.
            logger.info("Generating new Envoy configuration...")

            resources = fetch_resources(config_dir_path, k8s=k8s)
            aconf = Config()
            aconf.load_all(resources)

            if dump_aconf:
                with open(dump_aconf, "w") as output:
                    output.write(aconf.as_json())
                    output.write("\n")

            # If exit_on_error is set, log _errors and exit with status 1
            if exit_on_error and aconf.errors:
                raise Exception("errors in: {0}".format(', '.join(aconf.errors.keys())))

            ir = IR(aconf)

            if dump_ir:
                with open(dump_ir, "w") as output:
                    output.write(ir.as_json())
                    output.write("\n")

            v1config = V1Config(ir)
            rc = RichStatus.OK(msg="huh")

            if rc:
                with open(output_json_path, "w") as output:
                    output.write(v1config.as_json())
                    output.write("\n")
            else:
                logger.error("Could not generate new Envoy configuration: %s" % rc.error)

        show_notices()
    except Exception as e:
        handle_exception("EXCEPTION from config", e,
                         config_dir_path=config_dir_path, output_json_path=output_json_path)

        # This is fatal.
        sys.exit(1)

def main():
    clize.run([config, dump, validate], alt=[version, showid],
              description="""
              Generate an Envoy config, or manage an Ambassador deployment. Use

              ambassador.py command --help

              for more help, or

              ambassador.py --version

              to see Ambassador's version.
              """)

if __name__ == "__main__":
    main()