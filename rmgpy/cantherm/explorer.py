#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#                                                                             #
# RMG - Reaction Mechanism Generator                                          #
#                                                                             #
# Copyright (c) 2002-2018 Prof. William H. Green (whgreen@mit.edu),           #
# Prof. Richard H. West (r.west@neu.edu) and the RMG Team (rmg_dev@mit.edu)   #
#                                                                             #
# Permission is hereby granted, free of charge, to any person obtaining a     #
# copy of this software and associated documentation files (the 'Software'),  #
# to deal in the Software without restriction, including without limitation   #
# the rights to use, copy, modify, merge, publish, distribute, sublicense,    #
# and/or sell copies of the Software, and to permit persons to whom the       #
# Software is furnished to do so, subject to the following conditions:        #
#                                                                             #
# The above copyright notice and this permission notice shall be included in  #
# all copies or substantial portions of the Software.                         #
#                                                                             #
# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR  #
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,    #
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE #
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER      #
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING     #
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER         #
# DEALINGS IN THE SOFTWARE.                                                   #
#                                                                             #
###############################################################################

import os
import numpy as np
import logging
import shutil
from copy import deepcopy

import rmgpy
from rmgpy.rmg.main import RMG
from rmgpy.rmg.model import CoreEdgeReactionModel
from rmgpy.data.rmg import getDB
from rmgpy.exceptions import InputError

class ExplorerJob(object):
    def __init__(self, source, pdepjob, explore_tol, energy_tol=np.inf, flux_tol=0.0, 
                 bathGas=None, maximumRadicalElectrons=np.inf):
        self.source = source
        self.explore_tol = explore_tol
        self.energy_tol = energy_tol
        self.flux_tol = flux_tol
        self.maximumRadicalElectrons = maximumRadicalElectrons
        
        self.pdepjob = pdepjob
        
        if not hasattr(self.pdepjob,'outputFile'):
            self.pdepjob.outputFile = None
        
        if bathGas:
            self.bathGas = bathGas
        elif self.pdepjob.network and self.pdepjob.network.bathGas:
            self.bathGas = self.pdepjob.network.bathGas
        else:
            raise InputError('bathGas not specified in explorer block')

    def copy(self):
        """
        Return a copy of the explorer job.
        """
        return ExplorerJob(
            source=deepcopy(self.source),
            pdepjob=self.pdepjob,
            explore_tol=self.explore_tol,
            energy_tol=self.energy_tol,
            flux_tol=self.flux_tol
        )
        
    def execute(self, outputFile, plot, format='pdf', print_summary=True, speciesList=None, thermoLibrary=None, kineticsLibrary=None):
        
        logging.info('Exploring network...')
        
        rmg = RMG()
        
        rmg.speciesConstraints = {'allowed' : ['input species', 'seed mechanisms', 'reaction libraries'], 'maximumRadicalElectrons' : self.maximumRadicalElectrons, 'explicitlyAllowedMolecules': []}

        rmgpy.rmg.input.rmg = rmg
        
        reaction_model = CoreEdgeReactionModel()
        
        reaction_model.pressureDependence = self.pdepjob
        
        reaction_model.pressureDependence.rmgmode = True
        
        if outputFile:
            reaction_model.pressureDependence.outputFile = os.path.dirname(outputFile)
        
        kineticsDatabase = getDB('kinetics')
        thermoDatabase = getDB('thermo')
        
        thermoDatabase.libraries['thermojobs'] = thermoLibrary
        thermoDatabase.libraryOrder.insert(0,'thermojobs')
        
        kineticsDatabase.libraries['kineticsjobs'] = kineticsLibrary
        kineticsDatabase.libraryOrder.insert(0,('kineticsjobs','Reaction Library'))
        
        jobRxns = [rxn for rxn in reaction_model.core.reactions]
        
        self.jobRxns = jobRxns
        
        if outputFile is not None:
            if not os.path.exists(os.path.join(reaction_model.pressureDependence.outputFile,'pdep')):
                os.mkdir(os.path.join(reaction_model.pressureDependence.outputFile,'pdep'))
            else:
                shutil.rmtree(os.path.join(reaction_model.pressureDependence.outputFile,'pdep'))
                os.mkdir(os.path.join(reaction_model.pressureDependence.outputFile,'pdep'))
            
        #get the molecular formula for the network
        
        mmol = None
        for spc in self.source:
            if mmol:
                mmol.merge(spc.molecule[0])
            else:
                mmol = spc.molecule[0]

        form = mmol.getFormula()
        
        for spec in self.bathGas.keys()+self.source:
            nspec,isNew = reaction_model.makeNewSpecies(spec,reactive=False)
            flags = np.array([s.molecule[0].getFormula()==form for s in reaction_model.core.species])
            reaction_model.enlarge(nspec,reactEdge=False,unimolecularReact=flags,
                    bimolecularReact=np.zeros((len(reaction_model.core.species),len(reaction_model.core.species))))
        
        reaction_model.addSeedMechanismToCore('kineticsjobs')
        
        for lib in kineticsDatabase.libraryOrder:
            if lib[0] != 'kineticsjobs':
                reaction_model.addReactionLibraryToEdge(lib[0])
        
        for spc in reaction_model.core.species:
            for i,item in enumerate(self.source):
                if spc.isIsomorphic(item):
                    self.source[i] = spc
        
        #react initial species
        flags = np.array([s.molecule[0].getFormula()==form for s in reaction_model.core.species])
        reaction_model.enlarge(reactEdge=True,unimolecularReact=flags,
                      bimolecularReact=np.zeros((len(reaction_model.core.species),len(reaction_model.core.species))))
        
        #find the network we're interested in
        for nwk in reaction_model.networkList:
            if set(nwk.source) == set(self.source):
                self.source = nwk.source
                network = nwk
                break
        else:
            raise ValueError('did not generate a network with the requested source.  This usually means no unimolecular reactions were \
                             generated for the source.  Note that library reactions that are not properly flagged as elementary_high_p can\
                             replace RMG generated reactions that would otherwise be part of networks.')
        
        network.bathGas = self.bathGas
        
        self.network = network
        
        #determine T and P combinations
        
        if self.pdepjob.Tlist:
            Tlist = self.pdepjob.Tlist.value_si
        else:
            Tlist = np.linspace(self.pdepjob.Tmin.value_si,self.pdepjob.Tmax.value_si,self.pdepjob.Tcount)
            
        if self.pdepjob.Plist:
            Plist = self.pdepjob.Plist.value_si
        else:
            Plist = np.linspace(self.pdepjob.Pmin.value_si,self.pdepjob.Pmax.value_si,self.pdepjob.Pcount)
            
        #generate the network
        
        forbiddenStructures = getDB('forbidden')
        incomplete = True
        
        while incomplete:
            incomplete = False
            for T in Tlist:
                for P in Plist:
                    if network.getLeakCoefficient(T=T,P=P) > self.explore_tol:
                        incomplete = True
                        spc = network.getMaximumLeakSpecies(T=T,P=P)
                        if forbiddenStructures.isMoleculeForbidden(spc.molecule[0]):
                            reaction_model.removeSpeciesFromEdge(reaction_model.reactionSystems,spc)
                            reaction_model.removeEmptyPdepNetworks()
                            logging.error(spc.label)
                        else:
                            logging.info('adding new isomer {0} to network'.format(spc))
                            flags = np.array([s.molecule[0].getFormula()==form for s in reaction_model.core.species])
                            reaction_model.enlarge((network,spc),reactEdge=False,unimolecularReact=flags,
                                              bimolecularReact=np.zeros((len(reaction_model.core.species),len(reaction_model.core.species))))
                        
                            flags = np.array([s.molecule[0].getFormula()==form for s in reaction_model.core.species])
                            reaction_model.enlarge(reactEdge=True,unimolecularReact=flags,
                                              bimolecularReact=np.zeros((len(reaction_model.core.species),len(reaction_model.core.species))))
        
        rmRxns = []               
        for rxn in network.pathReactions: #remove reactions with forbidden species
            for r in rxn.reactants+rxn.products:
                if forbiddenStructures.isMoleculeForbidden(r.molecule[0]):
                    rmRxns.append(rxn)
        
        for rxn in rmRxns:
            logging.info('Removing forbidden reaction: {0}'.format(rxn))
            network.pathReactions.remove(rxn)
            
        #clean up output files
        if outputFile is not None:
            path = os.path.join(reaction_model.pressureDependence.outputFile,'pdep')
            for name in os.listdir(path):
                if name.endswith('.py') and '_' in name:
                    if name.split('_')[-1].split('.')[0] != str(len(network.isomers)):
                        os.remove(os.path.join(path,name))
                    else:
                        os.rename(os.path.join(path,name),os.path.join(path,'network_full.py'))    
        
        warns = []
        
        for rxn in jobRxns:
            if rxn not in network.pathReactions:
                warns.append('Reaction {0} in the input file was not explored during network expansion and was not included in the full network.  This is likely because your explore_tol value is too high.'.format(rxn))
        
        #reduction process
        
        if self.energy_tol != np.inf or self.flux_tol != 0.0:
            
            rxnSet = None
            
            for T in Tlist:
                if self.energy_tol != np.inf:
                    rxns = network.get_energy_filtered_reactions(T,self.energy_tol)
                    if rxnSet is not None:
                        rxnSet &= set(rxns)
                    else:
                        rxnSet = set(rxns)
                    
                for P in Plist:
                    if self.flux_tol != 0.0:
                        rxns = network.get_rate_filtered_reactions(T,P,self.flux_tol)
                        if rxnSet is not None:
                            rxnSet &= set(rxns)
                        else:
                            rxnSet = set(rxns) 
                            
            logging.info('removing reactions during reduction:')
            for rxn in rxnSet:
                logging.info(rxn)
            
            network.remove_reactions(reaction_model,list(rxnSet))
        
            for rxn in jobRxns:
                if rxn not in network.pathReactions:
                    warns.append('Reaction {0} in the input file was not included in the reduced model.'.format(rxn))
    
        self.network = network
        
        self.pdepjob.network = network
        
        self.pdepjob.execute(outputFile, plot, format='pdf', print_summary=True)
        
        if warns != []:
            logging.info('\nOUTPUT WARNINGS:\n')
            for w in warns:
                logging.warning(w)
                