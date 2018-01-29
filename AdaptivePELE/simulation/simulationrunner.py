import time
import os
import json
import subprocess
import shutil
import string
import sys
import numpy as np
from AdaptivePELE.constants import constants, blockNames
from AdaptivePELE.simulation import simulationTypes
from AdaptivePELE.atomset import atomset, RMSDCalculator
from AdaptivePELE.utilities import utilities


class SimulationParameters:
    def __init__(self):
        self.processors = 0
        self.executable = ""
        self.templetizedControlFile = ""
        self.dataFolder = ""
        self.documentsFolder = ""
        self.iterations = 0
        self.peleSteps = 0
        self.seed = 0
        self.exitCondition = None
        self.boxCenter = None
        self.boxRadius = 20
        self.modeMovingBox = None
        self.runEquilibration = False
        self.equilibrationLength = 50
        self.destination = None
        self.origin = None
        self.equilibrationMode = ""


class SimulationRunner:
    def __init__(self, parameters):
        self.parameters = parameters
        self.processorsToClusterMapping = []

    def runSimulation(self, runningControlFile=""):
        pass

    def hasExitCondition(self):
        """
            Check if an exit condition has been set

            :returns: bool -- True if an exit condition is set
        """
        return self.parameters.exitCondition is not None

    def checkExitCondition(self, clustering, outputFolder):
        """
            Check if the exit condition has been met

            :param clustering: Clustering object
            :type clustering: :py:class:`.Clustering`

            :returns: bool -- True if the exit condition is met
        """
        if self.parameters.exitCondition.type == simulationTypes.EXITCONDITION_TYPE.METRICMULTIPLETRAJS:
            return self.parameters.exitCondition.checkExitCondition(outputFolder)
        else:
            return self.parameters.exitCondition.checkExitCondition(clustering)

    def makeWorkingControlFile(self, workingControlFilename, dictionary, inputTemplate=None):
        """
            Substitute the values in the templetized control file

            :param workingControlFilename: Name of the template control file
            :type workingControlFilename: str
            :param dictionary: Dictonary containing the parameters to substitute
                in the control file
            :param inputFileTemplate: Template control file
            :type inputFileTemplate: str
            :type dictionary: dict
        """
        if inputTemplate is None:
            with open(self.parameters.templetizedControlFile, "r") as inputFile:
                inputFileContent = inputFile.read()
        else:
            inputFileContent = inputTemplate

        inputFileTemplate = string.Template(inputFileContent)
        outputFileContent = inputFileTemplate.substitute(dictionary)
        with open(workingControlFilename, "w") as outputFile:
            outputFileContent = outputFileContent.replace("'", '"')
            outputFile.write(outputFileContent)

    def updateMappingProcessors(self, mapping):
        """
            Update the value of the processorsToClusterMapping, a list with the
            snapshot from which the trajectories will start in the next iteration

            :param mapping: List with the snapshot from which the trajectories
                will start in the next iteration
            :type mapping: list
        """
        self.processorsToClusterMapping = mapping[1:]+[mapping[0]]

    def writeMappingToDisk(self, epochDir):
        """
            Write the processorsToClusterMapping to disk

            :param epochDir: Name of the folder where to write the
                processorsToClusterMapping
            :type epochDir: str
        """
        if len(self.processorsToClusterMapping) == 0:
            return
        with open(epochDir+"/processorMapping.txt", "w") as f:
            f.write(':'.join(map(str, self.processorsToClusterMapping)))

    def readMappingFromDisk(self, epochDir):
        """
            Read the processorsToClusterMapping from disk

            :param epochDir: Name of the folder where to write the
                processorsToClusterMapping
            :type epochDir: str
        """
        try:
            with open(epochDir+"/processorMapping.txt") as f:
                self.processorsToClusterMapping = map(int, f.read().rstrip().split(':'))
        except IOError:
            sys.stderr.write("WARNING: processorMapping.txt not found, you might not be able to recronstruct fine-grained pathways\n")

    def setZeroMapping(self):
        """
            Set the processorsToClusterMapping to zero
        """
        self.processorsToClusterMapping = [0 for _ in xrange(1, self.parameters.processors)]


class PeleSimulation(SimulationRunner):
    def __init__(self, parameters):
        SimulationRunner.__init__(self, parameters)
        self.type = simulationTypes.SIMULATION_TYPE.PELE

    def createSymbolicLinks(self):
        """
            Create symbolic links to Data and Documents folder if they don't exist
        """
        if not os.path.islink("Data"):
            os.system("ln -s " + self.parameters.dataFolder + " Data")
        if not os.path.islink("Documents"):
            os.system("ln -s " + self.parameters.documentsFolder + " Documents")

    def selectInitialBoxCenter(self, initialStructuresAsString, resname):
        """
            Select the coordinates of the first box, currently as the center of
            mass of the first initial structure provided

            :param initialStructuresAsString: String containing the files of the initial structures
            :type initialStructuresAsString: str
            :param resname: Residue name of the ligand in the system pdb
            :type resname: str

            :returns str: -- string to be substitued in PELE control file
        """
        # This is a dictionary because it's prepared to be subtitued in the PELE
        # control files (i.e. JSON format)
        try:
            initialStructuresDict = json.loads(initialStructuresAsString.split(",")[0])
            initialStruct = str(initialStructuresDict['files'][0]['path'])
        except ValueError:
            # If a json valid string is not passed, interpret the input string
            # as a path to a file
            initialStruct = initialStructuresAsString

        PDBinitial = atomset.PDB()
        PDBinitial.initialise(initialStruct, resname=resname)
        return repr(PDBinitial.getCOM())

    def runSimulation(self, runningControlFile=""):
        """
            Run a short PELE simulation

            :param runningControlFile: PELE control file to run
            :type runningControlFile: str
        """
        self.createSymbolicLinks()

        toRun = ["mpirun -np " + str(self.parameters.processors), self.parameters.executable, runningControlFile]
        toRun = " ".join(toRun)
        print toRun
        startTime = time.time()
        proc = subprocess.Popen(toRun, stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
        print out
        if err:
            print err

        endTime = time.time()
        print "PELE took %.2f sec" % (endTime - startTime)

    def getEquilibrationControlFile(self, peleControlFileDict):
        """
            Filter unnecessary parameters and return a minimal PELE control
            file for equilibration runs

            :param peleControlFileDict: Dictionary with pele control file options
            :type peleControlFileDict: dict

            :returns: dict -- Dictionary with pele control file options
        """
        # Set small rotations and translations
        peleControlFileDict["commands"][0]["Perturbation"]["parameters"]["translationRange"] = 0.5
        peleControlFileDict["commands"][0]["Perturbation"]["parameters"]["rotationScalingFactor"] = 0.01
        # Remove dynamical changes in control file
        peleControlFileDict["commands"][0]["PeleTasks"][0].pop("exitConditions", None)
        peleControlFileDict["commands"][0]["PeleTasks"][0].pop("parametersChanges", None)

        return peleControlFileDict

    def getMetricColumns(self, JSONdict):
        """
            Extract the column of a similarity distance (RMSD or distance) from the pele control file

            :param JSONdict: Dictionary containing a parsed PELE control file
            :type JSONdict: dict

            :returns: int -- Column index of the similarity metric
        """
        hasRMSD = False
        RMSDCol = None
        distanceCol = None
        hasDistance = False
        for i, metricBlock in enumerate(JSONdict["commands"][0]["PeleTasks"][0]['metrics']):
            if 'rmsd' in metricBlock['type'].lower():
                hasRMSD = True
                RMSDCol = i+4
            elif 'distance' in metricBlock['type'].lower():
                hasDistance = True
                distanceCol = i+4
        if hasRMSD:
            return RMSDCol
        elif hasDistance:
            return distanceCol
        else:
            return None

    def equilibrate(self, initialStructures, outputPathConstants, reportFilename, outputPath, resname):
        """
            Run short simulation to equilibrate the system. It will run one
            such simulation for every initial structure and select appropiate
            structures to start the simulation

            :param initialStructures: Name of the initial structures to copy
            :type initialStructures: list of str
            :param outputPathConstants: Contains outputPath-related constants
            :type outputPathConstants: :py:class:`.OutputPathConstants`
            :param reportBaseFilename: Name of the file that contains the metrics of the snapshots to cluster
            :type reportBaseFilename: str
            :param outputPath: Path where trajectories are found
            :type outputPath: str
            :param resname: Residue name of the ligand in the system pdb
            :type resname: str

            :returns: list --  List with initial structures
        """
        newInitialStructures = []
        equilibrationPeleDict = {"PELE_STEPS": self.parameters.equilibrationLength, "SEED": self.parameters.seed}
        peleControlFileDict, templateNames = utilities.getPELEControlFileDict(self.parameters.templetizedControlFile)
        peleControlFileDict = self.getEquilibrationControlFile(peleControlFileDict)
        similarityColumn = self.getMetricColumns(peleControlFileDict)
        reportWildcard, trajWildcard = utilities.getReportAndTrajectoryWildcard(peleControlFileDict)

        for i, structure in enumerate(initialStructures):
            equilibrationOutput = os.path.join(outputPath, "equilibration_%d" % (i+1))
            equilibrationControlFile = outputPathConstants.tmpControlFilenameEqulibration % (i+1)
            utilities.makeFolder(equilibrationOutput)
            shutil.copyfile(structure, outputPathConstants.tmpInitialStructuresEquilibrationTemplate % (i+1))
            initialStructureString = self.createMultipleComplexesFilenames(1, outputPathConstants.tmpInitialStructuresEquilibrationTemplate, i+1, equilibration=True)
            equilibrationPeleDict["OUTPUT_PATH"] = equilibrationOutput
            equilibrationPeleDict["COMPLEXES"] = initialStructureString
            equilibrationPeleDict["BOX_CENTER"] = self.selectInitialBoxCenter(structure, resname)
            equilibrationPeleDict["BOX_RADIUS"] = 2
            print "Running equilibration for initial structure number %d" % (i+1)
            peleControlString = json.dumps(peleControlFileDict, indent=4)
            for key, value in templateNames.iteritems():
                # Remove double quote around template keys, so that PELE
                # understands the options
                peleControlString = peleControlString.replace(value, "$%s" % key)

            self.makeWorkingControlFile(equilibrationControlFile, equilibrationPeleDict, peleControlString)
            self.runSimulation(equilibrationControlFile)
            # Extract report, trajnames, metrics columns from pele control file
            reportNames = os.path.join(equilibrationOutput, reportWildcard)
            trajNames = os.path.join(equilibrationOutput, trajWildcard)
            if len(initialStructures) == 1 and self.parameters.equilibrationMode == blockNames.SimulationParams.equilibrationLastSnapshot:
                newStructure = self.selectEquilibrationLastSnapshot(self.parameters.processors, trajNames)
            else:
                newStructure = self.selectEquilibratedStructure(self.parameters.processors, similarityColumn, resname, trajNames, reportNames)

            for j, struct in enumerate(newStructure):
                newStructurePath = os.path.join(equilibrationOutput, 'equilibration_struc_%d_%d.pdb' % (i+1, j+1))
                with open(newStructurePath, "w") as fw:
                    fw.write(struct)
                newInitialStructures.append(newStructurePath)
        return newInitialStructures

    def selectEquilibrationLastSnapshot(self, nTrajs, trajWildcard):
        """
            Select the last snapshot of each trajectory as a  representative
            initial structure from the equilibration run

            :param nTrajs: Number of trajectories
            :type nTrajs: int
            :param trajWildcard: Templetized path to trajectory files"
            :type trajWildcard: str

            :returns: list -- List with the pdb snapshots of the representatives structures
        """
        return [utilities.getSnapshots(trajWildcard % ij)[-1] for ij in xrange(1, nTrajs)]

    def selectEquilibratedStructure(self, nTrajs, similarityColumn, resname, trajWildcard, reportWildcard):
        """
            Select a representative initial structure from the equilibration
            run

            :param nTrajs: Number of trajectories
            :type nTrajs: int
            :param similarityColumn: Column number of the similarity metric
                (RMSD or distance)
            :type similarityColumn: int
            :param resname: Name of the ligand in the pdb
            :type resname: str
            :param trajWildcard: Templetized path to trajectory files"
            :type trajWildcard: str
            :param reportWildcard: Templetized path to report files"
            :type reportWildcard: str

            :returns: list -- List with the pdb snapshots of the representatives structures
        """
        energyColumn = 3
        values = []
        indices = []
        rowIndex = 0
        if similarityColumn is None:
            RMSDCalc = RMSDCalculator.RMSDCalculator()
            initial = atomset.PDB()
        else:
            cols = sorted([energyColumn, similarityColumn])

        for i in xrange(1, nTrajs):
            indices.append(rowIndex)
            report = np.loadtxt(reportWildcard % i)
            if similarityColumn is None:
                snapshots = utilities.getSnapshots(trajWildcard % i)
                report_values = []
                if i == 1:
                    initial.initialise(snapshots.pop(0), resname=resname)
                    report_values.append([0, report[0, energyColumn]])
                    report = report[1:, :]
                for j, snap in enumerate(snapshots):
                    pdbConformation = atomset.PDB()
                    pdbConformation.initialise(snap, resname=resname)
                    report_values.append([RMSDCalc.computeRMSD(initial, pdbConformation), report[j, energyColumn]])
            else:
                report_values = report[:, cols]
            values.extend(report_values)
            rowIndex += len(report_values)

        values = np.array(values)
        if energyColumn > similarityColumn or similarityColumn is None:
            similarityColumn, energyColumn = range(2)
        else:
            energyColumn, similarityColumn = range(2)
        maxEnergy = values.max(axis=0)[energyColumn]
        # Substract the max value so all values will be negative (avoid sign problems)
        values[:, energyColumn] -= maxEnergy
        minEnergy = values.min(axis=0)[energyColumn]
        # Normalize to the minimum value
        values[:, energyColumn] /= minEnergy
        freq, bins = np.histogram(values[:, similarityColumn])
        freq = np.divide(freq, np.float(np.sum(freq)))
        # Get center of the bins
        centers = (bins[:-1]+bins[1:])/2.0
        for row in values:
            row[similarityColumn] = freq[np.argmin(np.abs(row[similarityColumn] - centers))]
        distance = values.sum(axis=1)
        indexSelected = np.argmax(distance)
        # Get trajectory and snapshot number from the index selected
        trajNum = len(indices)-1
        for i, index in enumerate(indices):
            if index == indexSelected:
                trajNum = i
                break
            elif indexSelected < index:
                trajNum = i-1
                break
        snapshotNum = indexSelected-indices[trajNum]
        # trajectories are 1-indexed
        trajNum += 1
        # return as list for compatibility with selectEquilibrationLastSnapshot
        return [utilities.getSnapshots(trajWildcard % trajNum)[snapshotNum]]

    def createMultipleComplexesFilenames(self, numberOfSnapshots, tmpInitialStructuresTemplate, iteration, equilibration=False):
        """
            Creates the string to substitute the complexes in the PELE control file

            :param numberOfSnapshots: Number of complexes to write
            :type numberOfSnapshots: int
            :param tmpInitialStructuresTemplate: Template with the name of the initial strutctures
            :type tmpInitialStructuresTemplate: str
            :param iteration: Epoch number
            :type iteration: int
            :param equilibration: Flag to mark wether the complexes are part of an
                equilibration run
            :type equilibration: bool

            :returns: str -- jsonString to be substituted in PELE control file
        """
        jsonString = ["\n"]
        for i in range(numberOfSnapshots-1):
            if equilibration:
                jsonString.append(constants.inputFileTemplate % (tmpInitialStructuresTemplate % (iteration)) + ",\n")
            else:
                jsonString.append(constants.inputFileTemplate % (tmpInitialStructuresTemplate % (iteration, i)) + ",\n")
        if equilibration:
            jsonString.append(constants.inputFileTemplate % (tmpInitialStructuresTemplate % (iteration)))
        else:
            jsonString.append(constants.inputFileTemplate % (tmpInitialStructuresTemplate % (iteration, numberOfSnapshots-1)))
        return "".join(jsonString)


class TestSimulation(SimulationRunner):
    """
        Class used for testing
    """
    def __init__(self, parameters):
        SimulationRunner.__init__(self, parameters)
        self.type = simulationTypes.SIMULATION_TYPE.TEST
        self.copied = False
        self.parameters = parameters

    def runSimulation(self, runningControlFile=""):
        """
            Copy file to test the rest of the AdaptivePELE procedure
        """
        if not self.copied:
            if os.path.exists(self.parameters.destination):
                shutil.rmtree(self.parameters.destination)
            shutil.copytree(self.parameters.origin, self.parameters.destination)
            self.copied = True

    def makeWorkingControlFile(self, workingControlFilename, dictionary):
        pass


class ClusteringExitCondition:
    def __init__(self, ntrajs):
        self.clusterNum = 0
        self.ntrajs = ntrajs
        self.type = simulationTypes.EXITCONDITION_TYPE.CLUSTERING

    def checkExitCondition(self, clustering):
        """
            Iterate over all unchecked cluster and check if the exit condtion
            is met

            :param clustering: Clustering object
            :type clustering: :py:class:`.Clustering`

            :returns: bool -- Returns True if the exit condition has been met
        """
        newClusterNum = clustering.getNumberClusters()
        clusterDiff = newClusterNum - self.clusterNum
        self.clusterNum = newClusterNum
        return clusterDiff < 0.1*self.ntrajs


class MetricExitCondition:
    def __init__(self, metricCol, metricValue, condition):
        self.metricCol = metricCol
        self.metricValue = metricValue
        self.type = simulationTypes.EXITCONDITION_TYPE.METRIC
        if condition == ">":
            self.condition = lambda x, y: x > y
        else:
            self.condition = lambda x, y: x < y

    def checkExitCondition(self, clustering):
        """
            Iterate over all clusters and check if the exit condtion
            is met

            :param clustering: Clustering object
            :type clustering: :py:class:`.Clustering`

            :returns: bool -- Returns True if the exit condition has been met
        """
        for cluster in clustering.clusters.clusters:
            metric = cluster.getMetricFromColumn(self.metricCol)

            if metric is not None and self.condition(metric, self.metricValue):
                return True
        return False


class MetricMultipleTrajsExitCondition:
    def __init__(self, metricCol, metricValue, condition, reportWildCard, numTrajs, nProcessors):
        self.metricCol = metricCol
        self.metricValue = metricValue
        self.type = simulationTypes.EXITCONDITION_TYPE.METRICMULTIPLETRAJS
        self.numTrajs = numTrajs
        self.nProcessors = nProcessors
        self.trajsFound = 0
        if condition == ">":
            self.condition = lambda x, y: x.max() > y
        else:
            self.condition = lambda x, y: x.min() < y
        self.report = reportWildCard

    def checkExitCondition(self, outputFolder):
        """
            Iterate over all reports and check if the exit condtion
            is met

            :param clustering: Clustering object
            :type clustering: :py:class:`.Clustering`

            :returns: bool -- Returns True if the exit condition has been met
        """
        for j in range(1, self.nProcessors):
            report = np.loadtxt(os.path.join(outputFolder, self.report % j))
            if self.condition(report[:, self.metricCol], self.metricValue):
                self.trajsFound += 1
        return self.trajsFound >= self.numTrajs


class RunnerBuilder:
    def build(self, simulationRunnerBlock):
        """
            Build the selected  SimulationRunner object

            :param simulationRunnerBlock: Block of the control file
                corresponding to the simulation step
            :type simulationRunnerBlock: dict

            :returns: :py:class:`.SimulationRunner` -- SimulationRunner object
                selected
        """
        simulationType = simulationRunnerBlock[blockNames.SimulationType.type]
        paramsBlock = simulationRunnerBlock[blockNames.SimulationParams.params]
        params = SimulationParameters()
        if simulationType == blockNames.SimulationType.pele:
            params.processors = paramsBlock[blockNames.SimulationParams.processors]
            params.dataFolder = paramsBlock.get(blockNames.SimulationParams.dataFolder, constants.DATA_FOLDER)
            params.documentsFolder = paramsBlock.get(blockNames.SimulationParams.documentsFolder, constants.DOCUMENTS_FOLDER)
            params.executable = paramsBlock.get(blockNames.SimulationParams.executable, constants.PELE_EXECUTABLE)
            params.templetizedControlFile = paramsBlock[blockNames.SimulationParams.templetizedControlFile]
            params.iterations = paramsBlock[blockNames.SimulationParams.iterations]
            params.peleSteps = paramsBlock[blockNames.SimulationParams.peleSteps]
            params.seed = paramsBlock[blockNames.SimulationParams.seed]
            params.modeMovingBox = paramsBlock.get(blockNames.SimulationParams.modeMovingBox)
            params.boxCenter = paramsBlock.get(blockNames.SimulationParams.boxCenter)
            params.boxRadius = paramsBlock.get(blockNames.SimulationParams.boxRadius, 20)
            params.runEquilibration = paramsBlock.get(blockNames.SimulationParams.runEquilibration, False)
            params.equilibrationMode = paramsBlock.get(blockNames.SimulationParams.equilibrationMode, blockNames.SimulationParams.equilibrationSelect)
            params.equilibrationLength = paramsBlock.get(blockNames.SimulationParams.equilibrationLength, 50)
            exitConditionBlock = paramsBlock.get(blockNames.SimulationParams.exitCondition, None)
            if exitConditionBlock:
                exitConditionBuilder = ExitConditionBuilder()
                params.exitCondition = exitConditionBuilder.build(exitConditionBlock, params.templetizedControlFile, params.processors)

            return PeleSimulation(params)
        elif simulationType == blockNames.SimulationType.md:
            pass
        elif simulationType == blockNames.SimulationType.test:
            params.processors = paramsBlock[blockNames.SimulationParams.processors]
            params.destination = paramsBlock[blockNames.SimulationParams.destination]
            params.origin = paramsBlock[blockNames.SimulationParams.origin]
            params.iterations = paramsBlock[blockNames.SimulationParams.iterations]
            params.peleSteps = paramsBlock[blockNames.SimulationParams.peleSteps]
            params.seed = paramsBlock[blockNames.SimulationParams.seed]
            return TestSimulation(params)
        else:
            sys.exit("Unknown simulation type! Choices are: " + str(simulationTypes.SIMULATION_TYPE_TO_STRING_DICTIONARY.values()))


class ExitConditionBuilder:
    def build(self, exitConditionBlock, templetizedControlFile, nProcessors):
        """
            Build the selected exit condition object

            :param exitConditionBlock: Block of the control file
                corresponding to the exit condition
            :type exitConditionBlock: dict

            :returns: :py:class:`.MetricExitCondition` -- MetricExitCondition object
                selected
        """
        exitConditionType = exitConditionBlock[blockNames.ExitConditionType.type]
        exitConditionParams = exitConditionBlock[blockNames.SimulationParams.params]
        if exitConditionType == blockNames.ExitConditionType.metric:
            metricCol = exitConditionParams[blockNames.SimulationParams.metricCol]
            metricValue = exitConditionParams[blockNames.SimulationParams.exitValue]
            condition = exitConditionParams.get(blockNames.SimulationParams.condition, "<")
            if condition not in [">", "<"]:
                raise ValueError("In MetricExitCondition the parameter condition only accepts > or <, but %s was passed" % condition)
            return MetricExitCondition(metricCol, metricValue, condition)
        elif exitConditionType == blockNames.ExitConditionType.metricMultipleTrajs:
            metricCol = exitConditionParams[blockNames.SimulationParams.metricCol]
            metricValue = exitConditionParams[blockNames.SimulationParams.exitValue]
            numTrajs = exitConditionParams[blockNames.SimulationParams.numTrajs]
            condition = exitConditionParams.get(blockNames.SimulationParams.condition, "<")
            if condition not in [">", "<"]:
                raise ValueError("In MetricMultipleTrajsExitCondition the parameter condition only accepts > or <, but %s was passed" % condition)
            peleControlFileDict, _ = utilities.getPELEControlFileDict(templetizedControlFile)
            reportWildCard, _ = utilities.getReportAndTrajectoryWildcard(peleControlFileDict)
            return MetricMultipleTrajsExitCondition(metricCol, metricValue, condition, reportWildCard, numTrajs, nProcessors)
        elif exitConditionType == blockNames.ExitConditionType.clustering:
            ntrajs = exitConditionParams[blockNames.SimulationParams.trajectories]
            return ClusteringExitCondition(ntrajs)
        else:
            sys.exit("Unknown exit condition type! Choices are: " + str(simulationTypes.EXITCONDITION_TYPE_TO_STRING_DICTIONARY.values()))
