"""
Subsets of octrees

Author: Matthew Turk <matthewturk@gmail.com>
Affiliation: Columbia University
Homepage: http://yt-project.org/
License:
  Copyright (C) 2013 Matthew Turk.  All Rights Reserved.

  This file is part of yt.

  yt is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import numpy as np

from yt.data_objects.data_containers import \
    YTFieldData, \
    YTDataContainer, \
    YTSelectionContainer
from .field_info_container import \
    NeedsGridType, \
    NeedsOriginalGrid, \
    NeedsDataField, \
    NeedsProperty, \
    NeedsParameter
import yt.geometry.particle_deposit as particle_deposit
from yt.funcs import *

class OctreeSubset(YTSelectionContainer):
    _spatial = True
    _num_ghost_zones = 0
    _num_zones = 2
    _type_name = 'octree_subset'
    _skip_add = True
    _con_args = ('base_region', 'domain', 'pf')
    _container_fields = ("dx", "dy", "dz")
    _domain_offset = 0
    _num_octs = -1

    def __init__(self, base_region, domain, pf):
        self.field_data = YTFieldData()
        self.field_parameters = {}
        self.domain = domain
        self.domain_id = domain.domain_id
        self.pf = domain.pf
        self.hierarchy = self.pf.hierarchy
        self.oct_handler = domain.oct_handler
        self._last_mask = None
        self._last_selector_id = None
        self._current_particle_type = 'all'
        self._current_fluid_type = self.pf.default_fluid_type
        self.base_region = base_region
        self.base_selector = base_region.selector

    def _generate_container_field(self, field):
        if self._current_chunk is None:
            self.hierarchy._identify_base_chunk(self)
        if field == "dx":
            return self._current_chunk.fwidth[:,0]
        elif field == "dy":
            return self._current_chunk.fwidth[:,1]
        elif field == "dz":
            return self._current_chunk.fwidth[:,2]
        else:
            raise RuntimeError

    def __getitem__(self, key):
        tr = super(OctreeSubset, self).__getitem__(key)
        try:
            fields = self._determine_fields(key)
        except YTFieldTypeNotFound:
            return tr
        finfo = self.pf._get_field_info(*fields[0])
        if not finfo.particle_type:
            # We may need to reshape the field, if it is being queried from
            # field_data.  If it's already cached, it just passes through.
            if len(tr.shape) < 4:
                tr = self._reshape_vals(tr)
            return tr
        return tr

    def _reshape_vals(self, arr):
        if len(arr.shape) == 4: return arr
        nz = self._num_zones + 2*self._num_ghost_zones
        n_oct = arr.shape[0] / (nz**3.0)
        arr = arr.reshape((nz, nz, nz, n_oct), order="F")
        arr = np.asfortranarray(arr)
        return arr

    _domain_ind = None

    @property
    def domain_ind(self):
        if self._domain_ind is None:
            di = self.oct_handler.domain_ind(self.selector)
            self._domain_ind = di
        return self._domain_ind

    def deposit(self, positions, fields = None, method = None):
        # Here we perform our particle deposition.
        cls = getattr(particle_deposit, "deposit_%s" % method, None)
        if cls is None:
            raise YTParticleDepositionNotImplemented(method)
        nvals = (2, 2, 2, (self.domain_ind >= 0).sum())
        op = cls(nvals) # We allocate number of zones, not number of octs
        op.initialize()
        mylog.debug("Depositing %s particles into %s Octs",
            positions.shape[0], nvals[-1])
        op.process_octree(self.oct_handler, self.domain_ind, positions, fields,
            self.domain_id, self._domain_offset)
        vals = op.finalize()
        if vals is None: return
        return np.asfortranarray(vals)

    def select_icoords(self, dobj):
        d = self.oct_handler.icoords(self.selector, domain_id = self.domain_id,
                                     num_octs = self._num_octs)
        self._num_octs = d.shape[0] / 8
        tr = self.oct_handler.selector_fill(dobj.selector, d, None, 0, 3,
                                            domain_id = self.domain_id)
        return tr

    def select_fcoords(self, dobj):
        d = self.oct_handler.fcoords(self.selector, domain_id = self.domain_id,
                                     num_octs = self._num_octs)
        self._num_octs = d.shape[0] / 8
        tr = self.oct_handler.selector_fill(dobj.selector, d, None, 0, 3,
                                            domain_id = self.domain_id)
        return tr

    def select_fwidth(self, dobj):
        d = self.oct_handler.fwidth(self.selector, domain_id = self.domain_id,
                                  num_octs = self._num_octs)
        self._num_octs = d.shape[0] / 8
        tr = self.oct_handler.selector_fill(dobj.selector, d, None, 0, 3,
                                            domain_id = self.domain_id)
        return tr

    def select_ires(self, dobj):
        d = self.oct_handler.ires(self.selector, domain_id = self.domain_id,
                                  num_octs = self._num_octs)
        self._num_octs = d.shape[0] / 8
        tr = self.oct_handler.selector_fill(dobj.selector, d, None, 0, 1,
                                            domain_id = self.domain_id)
        return tr

    def select(self, selector, source, dest, offset):
        n = self.oct_handler.selector_fill(selector, source, dest, offset,
                                           domain_id = self.domain_id)
        return n

    def count(self, selector):
        if id(selector) == self._last_selector_id:
            if self._last_mask is None: return 0
            return self._last_mask.sum()
        self.select(selector)
        return self.count(selector)

    def count_particles(self, selector, x, y, z):
        # We don't cache the selector results
        count = selector.count_points(x,y,z)
        return count

    def select_particles(self, selector, x, y, z):
        mask = selector.select_points(x,y,z)
        return mask

class ParticleOctreeSubset(OctreeSubset):
    # Subclassing OctreeSubset is somewhat dubious.
    # This is some subset of an octree.  Note that the sum of subsets of an
    # octree may multiply include data files.  While we can attempt to mitigate
    # this, it's unavoidable for many types of data storage on disk.
    _type_name = 'particle_octree_subset'
    _con_args = ('data_files', 'pf', 'min_ind', 'max_ind')
    domain_id = -1
    def __init__(self, base_region, data_files, pf, min_ind = 0, max_ind = 0):
        # The first attempt at this will not work in parallel.
        self.data_files = data_files
        self.field_data = YTFieldData()
        self.field_parameters = {}
        self.pf = pf
        self.hierarchy = self.pf.hierarchy
        self.oct_handler = pf.h.oct_handler
        self.min_ind = min_ind
        if max_ind == 0: max_ind = (1 << 63)
        self.max_ind = max_ind
        self._last_mask = None
        self._last_selector_id = None
        self._current_particle_type = 'all'
        self._current_fluid_type = self.pf.default_fluid_type
        self.base_region = base_region
        self.base_selector = base_region.selector
