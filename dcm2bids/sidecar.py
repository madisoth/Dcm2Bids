# -*- coding: utf-8 -*-

"""sidecars classes"""

import itertools
import logging
import os
import re
from collections import defaultdict, OrderedDict
from fnmatch import fnmatch

from dcm2bids.acquisition import Acquisition
from dcm2bids.utils.io import load_json
from dcm2bids.utils.utils import DEFAULT, convert_dir, splitext_


class Sidecar(object):
    """ A sidecar object

    Args:
        filename (str): Path of a JSON sidecar
        keyComp (list): A list of keys from the JSON sidecar to compare sidecars
                     default=["SeriesNumber","AcquisitionTime","SideCarFilename"]
    """

    def __init__(self, filename, compKeys=DEFAULT.compKeys):
        self._origData = {}
        self._data = {}
        self.filename = filename
        self.root, _ = splitext_(filename)
        self.data = filename
        self.compKeys = compKeys

    def __lt__(self, other):
        lts = []
        for key in self.compKeys:
            try:
                if all(key in d for d in (self.data, other.data)):
                    if self.data.get(key) == other.data.get(key):
                        lts.append(None)
                    else:
                        lts.append(self.data.get(key) < other.data.get(key))
                else:
                    lts.append(None)

            except Exception:
                lts.append(None)

        for lt in lts:
            if lt is not None:
                return lt

    def __eq__(self, other):
        return self.data == other.data

    def __hash__(self):
        return hash(self.filename)

    @property
    def origData(self):
        return self._origData

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, filename):
        """
        Args:
            filename (path): path of a JSON file

        Return:
            A dictionnary of the JSON content plus the SidecarFilename
        """
        try:
            data = load_json(filename)
        except Exception:
            data = {}
        self._origData = data.copy()
        data["SidecarFilename"] = os.path.basename(filename)
        self._data = data


class SidecarPairing(object):
    """
    Args:
        sidecars (list): List of Sidecar objects
        descriptions (list): List of dictionaries describing acquisitions
    """

    def __init__(self,
                 sidecars,
                 descriptions,
                 extractors=DEFAULT.extractors,
                 auto_extractor=DEFAULT.auto_extract_entities,
                 searchMethod=DEFAULT.searchMethod,
                 caseSensitive=DEFAULT.caseSensitive,
                 dupMethod=DEFAULT.dupMethod):
        self.logger = logging.getLogger(__name__)
        self._searchMethod = ""
        self._dupMethod = ""
        self.graph = OrderedDict()
        self.acquisitions = []
        self.extractors = extractors
        self.auto_extract_entities = auto_extractor
        self.sidecars = sidecars
        self.descriptions = descriptions
        self.searchMethod = searchMethod
        self.caseSensitive = caseSensitive
        self.dupMethod = dupMethod

    @property
    def searchMethod(self):
        return self._searchMethod

    @searchMethod.setter
    def searchMethod(self, value):
        """
        Checks if the search method is implemented
        Warns the user if not and fall back to default
        """
        if value in DEFAULT.searchMethodChoices:
            self._searchMethod = value

        else:
            self._searchMethod = DEFAULT.searchMethod
            self.logger.warning(f"'{value}' is not a search method implemented")
            self.logger.warning(f"Falling back to default: {DEFAULT.searchMethod}")
            self.logger.warning(
                f"Search methods implemented: {DEFAULT.searchMethodChoices}"
            )

    @property
    def dupMethod(self):
        return self._dupMethod

    @dupMethod.setter
    def dupMethod(self, value):
        """
        Checks if the duplicate method is implemented
        Warns the user if not and fall back to default
        """
        if value in DEFAULT.dupMethodChoices:
            self._dupMethod = value
        else:
            self._dupMethod = DEFAULT.dupMethod
            self.logger.warning(
                "Duplicate methods implemented: %s", DEFAULT.dupMethodChoices)
            self.logger.warning(f"{value} is not a duplicate method implemented.")
            self.logger.warning(f"Falling back to default: {DEFAULT.dupMethod}.")

    @property
    def caseSensitive(self):
        return self._caseSensitive

    @caseSensitive.setter
    def caseSensitive(self, value):
        if isinstance(value, bool):
            self._caseSensitive = value
        else:
            self._caseSensitive = DEFAULT.caseSensitive
            self.logger.warning(f"'{value}' is not a boolean")
            self.logger.warning(f"Falling back to default: {DEFAULT.caseSensitive}")
            self.logger.warning(f"Search methods implemented: {DEFAULT.caseSensitive}")

    def build_graph(self):
        """
        Test all the possible links between the list of sidecars and the
        description dictionaries and build a graph from it
        The graph is in a OrderedDict object. The keys are the Sidecars and
        the values are a list of possible descriptions

        Returns:
            A graph (OrderedDict)
        """
        graph = OrderedDict((_, []) for _ in self.sidecars)
        possibleLinks = itertools.product(self.sidecars, self.descriptions)
        for sidecar, description in possibleLinks:
            criteria = description.get("criteria", None)
            if criteria and self.isLink(sidecar.data, criteria):
                graph[sidecar].append(description)

        self.graph = graph

        return graph

    def isLink(self, data, criteria):
        """
        Args:
            data (dict): Dictionnary data of a sidecar
            criteria (dict): Dictionnary criteria

        Returns:
            boolean
        """

        def compare(name, pattern):
            name = str(name)
            if self.searchMethod == "re":
                return bool(re.match(pattern, name))
            else:
                pattern = str(pattern)
                if not self.caseSensitive:
                    name = name.lower()
                    pattern = pattern.lower()

                return fnmatch(name, pattern)

        def compare_list(name, pattern):
            try:
                subResult = [
                        len(name) == len(pattern),
                        isinstance(pattern, list),
                        ]
                for subName, subPattern in zip(name, pattern):
                    subResult.append(compare(subName, subPattern))
            except Exception:
                subResult = [False]
            return all(subResult)

        def compare_complex(name, pattern):
            sub_result = []
            compare_type = None
            try:
                for compare_type, patterns in pattern.items():
                    for sub_pattern in patterns:
                        if isinstance(name, list):
                            sub_result.append(compare_list(name, sub_pattern))
                        else:
                            sub_result.append(compare(name, sub_pattern))
            except Exception:
                sub_result = [False]
            if compare_type == "any":
                return any(sub_result)
            else:
                return False

        result = []

        for tag, pattern in criteria.items():
            name = data.get(tag, '')

            if isinstance(pattern, dict):
                result.append(compare_complex(name, pattern))
            elif isinstance(name, list):
                result.append(compare_list(name, pattern))
            else:
                result.append(compare(name, pattern))

        return all(result)

    def build_acquisitions(self, participant):
        """
        Args:
            participant (Participant): Participant object to create acquisitions
        Returns:
            A list of acquisition objects
        """
        acquisitions_id = []
        acquisitions = []
        self.logger.info("Sidecar pairing:\n".upper())
        for sidecar, valid_descriptions in self.graph.items():
            sidecarName = os.path.basename(sidecar.root)

            # only one description for the sidecar
            if len(valid_descriptions) == 1:
                desc = valid_descriptions[0]
                desc, sidecar = self.searchDcmTagEntity(sidecar, desc)

                acq = Acquisition(participant,
                                  srcSidecar=sidecar, **desc)
                acq.setDstFile()

                if acq.id:
                    acquisitions_id.append(acq)
                else:
                    acquisitions.append(acq)

                self.logger.info(
                  f"{acq.dstFile.replace(f'{acq.participant.prefix}-', '')}"
                  f"<-  {sidecarName}")

            elif len(valid_descriptions) == 0:
                self.logger.info(f"No Pairing  <-  {sidecarName}")

            else:
                self.logger.warning(f"Several Pairing  <-  {sidecarName}")
                for desc in valid_descriptions:
                    acq = Acquisition(participant,
                                      **desc)
                    self.logger.warning(f"    ->  {acq.suffix}")

        self.acquisitions = acquisitions_id + acquisitions

        return self.acquisitions

    def searchDcmTagEntity(self, sidecar, desc):
        """
        Add DCM Tag to customEntities
        """
        descWithTask = desc.copy()
        concatenated_matches = {}
        entities = []

        if "customEntities" in desc.keys() or self.auto_extract_entities:
            if 'customEntities' in desc.keys():
                if isinstance(descWithTask["customEntities"], str):
                    descWithTask["customEntities"] = [descWithTask["customEntities"]]
            else:
                descWithTask["customEntities"] = []

            if self.auto_extract_entities:
                self.extractors.update(DEFAULT.auto_extractors)

            for dcmTag in self.extractors:
                if dcmTag in sidecar.data.keys():
                    dcmInfo = sidecar.data.get(dcmTag)
                    for regex in self.extractors[dcmTag]:
                        compile_regex = re.compile(regex)
                        if not isinstance(dcmInfo, list):
                            if compile_regex.search(str(dcmInfo)) is not None:
                                concatenated_matches.update(
                                  compile_regex.search(str(dcmInfo)).groupdict())
                        else:
                            for curr_dcmInfo in dcmInfo:
                                if compile_regex.search(curr_dcmInfo) is not None:
                                    concatenated_matches.update(
                                      compile_regex.search(curr_dcmInfo).groupdict())
                                    break

            if "customEntities" in desc.keys():
                entities = set(concatenated_matches.keys()).union(set(descWithTask["customEntities"]))

            if self.auto_extract_entities:
                auto_acq = '_'.join([descWithTask['datatype'], descWithTask["suffix"]])
                if auto_acq in DEFAULT.auto_entities:
                    # Check if these auto entities have been found before merging
                    auto_entities = set(concatenated_matches.keys()).intersection(set(DEFAULT.auto_entities[auto_acq]))
                    left_auto_entities = auto_entities.symmetric_difference(set(DEFAULT.auto_entities[auto_acq]))
                    if left_auto_entities:
                        self.logger.warning(f"{left_auto_entities} have not been found for datatype '{descWithTask['datatype']}' "
                                            f"and suffix '{descWithTask['suffix']}'.")
                    else:
                        entities = list(entities) + DEFAULT.auto_entities[auto_acq]
                        entities = list(set(entities))
                        descWithTask["customEntities"] = entities

            for curr_entity in entities:
                if curr_entity in concatenated_matches.keys():
                    if curr_entity == 'dir':
                        descWithTask["customEntities"] = list(map(lambda x: x.replace(curr_entity, '-'.join([curr_entity, convert_dir(concatenated_matches[curr_entity])])), descWithTask["customEntities"]))
                    elif curr_entity == 'task':
                        sidecar.data['TaskName'] = concatenated_matches[curr_entity]
                        descWithTask["customEntities"] = list(map(lambda x: x.replace(curr_entity, '-'.join([curr_entity, concatenated_matches[curr_entity]])), descWithTask["customEntities"]))
                    else:
                        descWithTask["customEntities"] = list(map(lambda x: x.replace(curr_entity, '-'.join([curr_entity, concatenated_matches[curr_entity]])), descWithTask["customEntities"]))

            # Remove entities without -
            for curr_entity in descWithTask["customEntities"]:
                if '-' not in curr_entity:
                    self.logger.info(f"Removing entity '{curr_entity}' since it "
                                     "does not fit the basic BIDS specification "
                                     "(Entity-Value)")
                    descWithTask["customEntities"].remove(curr_entity)

        return descWithTask, sidecar

    def find_runs(self):
        """
        Check if there is duplicate destination roots in the acquisitions
        and add '_run-' to the customEntities of the acquisition
        """

        def duplicates(seq):
            """ Find duplicate items in a list

            Args:
                seq (list)

            Yield:
                A tuple of 2 items (item, list of index)

            ref: http://stackoverflow.com/a/5419576
            """
            tally = defaultdict(list)
            for i, item in enumerate(seq):
                tally[item].append(i)

            for key, locs in tally.items():
                if len(locs) > 1:
                    yield key, locs

        dstRoots = [_.dstRoot for _ in self.acquisitions]

        templateDup = DEFAULT.runTpl
        if self.dupMethod == 'dup':
            templateDup = DEFAULT.dupTpl

        for dstRoot, dup in duplicates(dstRoots):
            self.logger.info(f"{dstRoot} has {len(dup)} runs")
            self.logger.info(f"Adding {self.dupMethod} information to the acquisition")
            if self.dupMethod == 'dup':
                dup = dup[0:-1]

            for runNum, acqInd in enumerate(dup):
                runStr = templateDup.format(runNum+1)
                self.acquisitions[acqInd].customEntities += runStr
                self.acquisitions[acqInd].setDstFile()
