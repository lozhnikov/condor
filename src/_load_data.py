# -----------------------------------------------------------------------------------------------------
# CONDOR
# Simulator for diffractive single-particle imaging experiments with X-ray lasers
# http://xfel.icm.uu.se/condor/
# -----------------------------------------------------------------------------------------------------
# Copyright 2014 Max Hantke, Filipe R.N.C. Maia, Tomas Ekeberg
# Condor is distributed under the terms of the GNU General Public License
# -----------------------------------------------------------------------------------------------------
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but without any warranty; without even the implied warranty of
# merchantability or fitness for a pariticular purpose. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
# -----------------------------------------------------------------------------------------------------
# General note:
# All variables are in SI units by default. Exceptions explicit by variable name.
# -----------------------------------------------------------------------------------------------------
import pickle

def load_atomic_scattering_factors(data_dir):
    with open('%s/sf.dat' % data_dir, 'r') as f:
        atomic_scattering_factors = pickle.load(f)
    return atomic_scattering_factors

def load_atomic_masses(data_dir):
    with open('%s/sw.dat' % data_dir, 'r') as f:
        atomic_masses = pickle.load(f)
    return atomic_masses

def load_atomic_numbers(data_dir):
    with open('%s/z.dat' % data_dir, 'r') as f:
        atomic_numbers = pickle.load(f)
    return atomic_numbers