"""Map canvas for the top view.

********************************************************************************

   Copyright 2008-2014 Deutsches Zentrum fuer Luft- und Raumfahrt e.V.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

********************************************************************************

This file is part of the Mission Support System User Interface (MSUI).

As Matplotlib's Basemap is primarily designed to produce static plots,
we derived a class MapCanvas to allow for a certain degree of
interactivity. MapCanvas extends Basemap by functionality to, for
instance, automatically draw a graticule. It also keeps references to
plotted map elements to allow the user to toggle their visibility, or
to redraw when map section (zoom/pan) or projection have been changed.

AUTHORS:
========

* Marc Rautenhaus (mr)

"""

# standard library imports
from datetime import datetime
import logging

# related third party imports
from PyQt4 import QtGui, QtCore  # Qt4 bindings
import numpy as np
import matplotlib
import matplotlib.path as mpath
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.mlab as mlab
import mpl_toolkits.basemap as basemap
import mpl_toolkits.basemap.pyproj as pyproj

# local application imports
import mpl_pathinteractor as mpl_pi
import flighttrack as ft
import trajectory_item_tree as titree


################################################################################
###                           CLASS MapCanvas                                ###
################################################################################

class MapCanvas(basemap.Basemap):
    """Derivative of mpl_toolkits.basemap, providing additional methods to
       automatically draw a graticule and to redraw specific map elements.
    """

    def __init__(self, identifier=None, CRS=None, BBOX_UNITS=None,
                 traj_item_tree=None, appearance=None, **kwargs):
        """New constructor automatically adds coastlines, continents, and
           a graticule to the map.

        Keyword arguments are the same as for mpl_toolkits.basemap.

        Additional arguments:
        CRS -- string describing the coordinate reference system of the map.
        BBOX_UNITS -- string describing the units of the map coordinates.
        
        """
        # Coordinate reference system identifier and coordinate system units.
        self.crs = CRS if CRS else self.crs if hasattr(self, "crs") else None
        self.bbox_units = BBOX_UNITS if BBOX_UNITS else self.bbox_units \
                          if hasattr(self, "bbox_units") else None

        # Dictionary containing map appearance settings.
        param_appearance = appearance if appearance else self.appearance \
                           if hasattr(self, "appearance") else {}
        default_appearance = {"draw_graticule": True,
                              "draw_coastlines": True,
                              "fill_waterbodies": True,
                              "fill_continents": True,
                              "colour_water": (153/255.,255/255.,255/255.,255/255.),
                              "colour_land": (204/255.,153/255.,102/255.,255/255.)}
        default_appearance.update(param_appearance)
        self.appearance = default_appearance

        # Identifier of this map canvas (used to query data structures that
        # are observed by different views).
        self.identifier = identifier if identifier else self.identifier \
                          if hasattr(self, "identifier") else None

        # Call the Basemap constructor. If a cylindrical projection was used
        # before, Basemap stores an EPSG code that will not be changed if
        # the Basemap constructor is called a second time. Hence, we have to
        # delete the attribute (mr, 08Feb2013).
        if hasattr(self, "epsg"): del self.epsg
        super(MapCanvas, self).__init__(**kwargs)
        self.kwargs = kwargs
        
        # Set up the map appearance.
        if self.appearance["draw_coastlines"]:
            self.map_coastlines = self.drawcoastlines()
            self.map_countries = self.drawcountries()
        else:
            self.map_coastlines = None
            self.map_countries = None
        if self.appearance["fill_waterbodies"]:
            self.map_boundary = self.drawmapboundary(fill_color=self.appearance["colour_water"])
        else:
            self.map_boundary = None
            
        # zorder = 0 is necessary to paint over the filled continents with
        # scatter() for drawing the flight tracks and trajectories.
        # Curiously, plot() works fine without this setting, but scatter()
        # doesn't.
        if self.appearance["fill_continents"]:
            self.map_continents = self.fillcontinents(color=self.appearance["colour_land"],
                                                      lake_color=self.appearance["colour_water"],
                                                      zorder=0)
        else:
            self.map_continents = None

        self.image = None

        # Print CRS identifier into the figure.
        if self.crs:
            if hasattr(self, "crs_text"):
                self.crs_text.set_text(self.crs)
            else:
                self.crs_text = self.ax.figure.text(0, 0, self.crs)

        if self.appearance["draw_graticule"]:
            try:
                self._draw_auto_graticule()
            except Exception, e:
                logging.error("ERROR: cannot plot graticule (message: %s)" % e)
        else:
            self.map_parallels = None
            self.map_meridians = None

        #self.warpimage() # disable fillcontinents when loading bluemarble
        self.ax.set_autoscale_on(False)

        # Connect to the trajectory item tree, if defined.
        self.traj_item_tree = traj_item_tree if traj_item_tree else \
                              self.traj_item_tree if \
                              hasattr(self, "traj_item_tree") else None
        if traj_item_tree:
            self.set_trajectory_tree(traj_item_tree)


    def set_identifier(self, identifier):
        self.identifier = identifier


    def set_axes_limits(self,ax=None):
        """See Basemap.set_axes_limits() for documentation.

        This function is overridden in MapCanvas as a workaround to a problem
        in Basemap.set_axes_limits() that occurs in interactive matplotlib
        mode. If matplotlib.is_interactive() is True, Basemap.set_axes_limits()
        tries to redraw the canvas by accessing the pylab figure manager.
        If the matplotlib object is embedded in a Qt4 application, this manager
        is not available and an exception is raised. Hence, the interactive
        mode is disabled here before the original Basemap.set_axes_limits()
        method is called. It is restored afterwards.
        """
        intact = matplotlib.is_interactive()
        matplotlib.interactive(False)
        super(MapCanvas, self).set_axes_limits(ax=ax)
        matplotlib.interactive(intact)


    def _draw_auto_graticule(self):
        """Draw an automatically spaced graticule on the map.
        """
        # Compute some map coordinates that are required below for the automatic
        # determination of which meridians and parallels to draw.
        axis = self.ax.axis()
        upperLeftCornerLon, upperLeftCornerLat = self.__call__(axis[0],
                                                               axis[3],
                                                               inverse=True)
        lowerRightCornerLon, lowerRightCornerLat = self.__call__(axis[1],
                                                                 axis[2],
                                                                 inverse=True)
        middleUpperBoundaryLon, middleUpperBoundaryLat = \
                                self.__call__(np.mean([axis[0], axis[1]]),
                                              axis[3], inverse=True)
        middleLowerBoundaryLon, middleLowerBoundaryLat = \
                                self.__call__(np.mean([axis[0], axis[1]]),
                                              axis[2], inverse=True)

        # Determine which parallels and meridians should be drawn.
        #   a) determine which are the minimum and maximum visible
        #      longitudes and latitudes, respectively. These
        #      values depend on the map projection.
        if self.projection in ['stere', 'lcc']:
            # For stereographic projections: Draw meridians from the minimum
            # longitude contained in the map at one of the four corners to the
            # maximum longitude at one of these corner points. If
            # the map centre is contained in the map, draw all meridians
            # around the globe.
#FIXME? This is only correct for polar stereographic projections.
            # Draw parallels from the min latitude contained in the map at
            # one of the four corners OR the middle top or bottom to the
            # maximum latitude at one of these six points.
            # If the map centre in contained in the map, replace either
            # start or end latitude by the centre latitude (whichever is
            # smaller/larger).

            # check if centre point of projection is contained in the map,
            # use projection coordinates for this test
            centre_x = self.projparams["x_0"]
            centre_y = self.projparams["y_0"]
            contains_centre = (centre_x < self.urcrnrx) \
                              and (centre_y < self.urcrnry)
            # merdidians
            if contains_centre:
                mapLonStart = -180.
                mapLonStop = 180.
            else:
                mapLonStart = min(upperLeftCornerLon, self.llcrnrlon,
                                  self.urcrnrlon, lowerRightCornerLon)
                mapLonStop = max(upperLeftCornerLon, self.llcrnrlon,
                                 self.urcrnrlon, lowerRightCornerLon)
            # parallels
            mapLatStart = min(middleLowerBoundaryLat, lowerRightCornerLat,
                              self.llcrnrlat,
                              middleUpperBoundaryLat, upperLeftCornerLat,
                              self.urcrnrlat)
            mapLatStop = max(middleLowerBoundaryLat, lowerRightCornerLat,
                             self.llcrnrlat,
                             middleUpperBoundaryLat, upperLeftCornerLat,
                             self.urcrnrlat)
            if contains_centre:
                centre_lat = self.projparams["lat_0"]
                mapLatStart = min(mapLatStart, centre_lat)
                mapLatStop = max(mapLatStop, centre_lat)
        else:
            # for other projections (preliminary): difference between the
            # lower left and the upper right corner.
            mapLonStart = self.llcrnrlon
            mapLonStop = self.urcrnrlon
            mapLatStart = self.llcrnrlat            
            mapLatStop = self.urcrnrlat

        #   b) parallels and meridians can be drawn with a spacing of
        #      >spacingValues< degrees. Determine the appropriate
        #      spacing for the lon/lat differences: about 10 lines
        #      should be drawn in each direction. (The following lines
        #      filter the spacingValues list for all spacing values
        #      that are larger than lat/lon difference / 10, then
        #      take the first value (first values that's larger)).
        spacingValues = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 40]
        deltaLon = mapLonStop - mapLonStart
        deltaLat = mapLatStop - mapLatStart
        spacingLon = [i for i in spacingValues if i > deltaLon/11.][0]
        spacingLat = [i for i in spacingValues if i > deltaLat/11.][0]

        #   c) parallels and meridians start at the first value in the
        #      spacingLon/Lat grid that's smaller than the lon/lat of the
        #      lower left corner; they stop at the first values in the
        #      grid that's larger than the lon/lat of the upper right corner.
        lonStart = np.floor(mapLonStart / spacingLon) * spacingLon
        lonStop = np.ceil(mapLonStop / spacingLon) * spacingLon
        latStart = np.floor(mapLatStart / spacingLat) * spacingLat
        latStop = np.ceil(mapLatStop / spacingLat) * spacingLat

        #   d) call the basemap methods to draw the lines in the determined
        #      range.
        self.map_parallels = self.drawparallels(np.arange(latStart, latStop,
                                                          spacingLat),
                                                labels = [1,1,0,0])
        self.map_meridians = self.drawmeridians(np.arange(lonStart, lonStop,
                                                          spacingLon),
                                                labels = [0,0,0,1])
        

    def set_graticule_visible(self, visible=True):
        """Set the visibily of the graticule.

        Removes a currently visible graticule by deleting internally stored
        line and text objects representing graticule lines and labels, then
        redrawing the map canvas.

        See http://www.mail-archive.com/matplotlib-users@lists.sourceforge.net/msg09349.html
        """
        self.appearance["draw_graticule"] = visible
        if visible and self.map_parallels is None and self.map_meridians is None:
            # Draw new graticule if visible is True and no current graticule
            # exists.
            self._draw_auto_graticule()
            # Update the figure canvas.
            self.ax.figure.canvas.draw()
        elif not visible and self.map_parallels and self.map_meridians:
            # If visible if False, remove current graticule if one exists.
            # Every item in self.map_parallels and self.map_meridians is
            # a tuple of a list of lines and a list of text labels.
            for item in self.map_parallels.values():
                for line in item[0]:
                    line.remove()
                for text in item[1]:
                    text.remove()
            for item in self.map_meridians.values():
                for line in item[0]:
                    line.remove()
                for text in item[1]:
                    text.remove()
            self.map_parallels = None
            self.map_meridians = None
            # Update the figure canvas.
            self.ax.figure.canvas.draw()


    def set_fillcontinents_visible(self, visible=True, land_color=None,
                                   lake_color=None):
        """Set the visibility of continent fillings.
        """
        if land_color is not None:
            self.appearance["colour_land"] = land_color
        if lake_color is not None:
            self.appearance["colour_water"] = lake_color
        self.appearance["fill_continents"] = visible
        
        if visible and self.map_continents is None:
            # zorder = 0 is necessary to paint over the filled continents with
            # scatter() for drawing the flight tracks and trajectories.
            # Curiously, plot() works fine without this setting, but scatter()
            # doesn't.
            self.map_continents = self.fillcontinents(color=self.appearance["colour_land"],
                                                      lake_color=self.appearance["colour_water"],
                                                      zorder=0)
            self.ax.figure.canvas.draw()
        elif not visible and self.map_continents:
            # Remove current fills. They are stored as a list of polygon patches
            # in self.map_continents.
            for patch in self.map_continents:
                patch.remove()
            self.map_continents = None
            self.ax.figure.canvas.draw()
        elif visible and self.map_continents:
            # Colours have changed: Remove the old fill and redraw.
            for patch in self.map_continents:
                patch.remove()
            self.map_continents = self.fillcontinents(color=self.appearance["colour_land"],
                                                      lake_color=self.appearance["colour_water"],
                                                      zorder=0)
            self.ax.figure.canvas.draw()
                     

    def set_coastlines_visible(self, visible=True):
        """Set the visibility of coastlines and country borders.
        """
        self.appearance["draw_coastlines"] = visible
        if visible and self.map_coastlines is None and self.map_countries is None:
            self.map_coastlines = self.drawcoastlines()
            self.map_countries = self.drawcountries()
            self.ax.figure.canvas.draw()
        elif not visible and self.map_coastlines and self.map_countries:
            self.map_coastlines.remove()
            self.map_countries.remove()
            del self.cntrysegs
            self.map_coastlines = None
            self.map_countries = None
            self.ax.figure.canvas.draw()
            

    def set_mapboundary_visible(self, visible=True, bg_color='#99ffff'):
        """
        """
#TODO: This doesn't work. Removing the map background only makes sense
#      if there's a second image underneath this map. Maybe we should work
#      with alpha values instead.
        self.appearance["fill_waterbodies"] = visible
        self.appearance["colour_water"] = bg_color
        
        if not visible and self.map_boundary:
            self.map_boundary.remove()
            self.map_boundary = None
            self.ax.figure.canvas.draw()
        elif visible:
            self.map_boundary = self.drawmapboundary(fill_color=bg_color)
            self.ax.figure.canvas.draw()


    def update_with_coordinate_change(self, kwargs_update=None):
        """Redraws the entire map. This is necessary after zoom/pan operations.

        Determines corner coordinates of the current axes, removes all items
        belonging the the current map and draws a new one by calling
        self.__init__().

        DRAWBACK of this approach is that the map coordinate system changes, as
        basemap always takes the lower left axis corner as (0,0). This means
        that all other objects on the matplotlib canvas (flight track, markers,
        ..) will be incorrectly placed after a redraw. Their coordinates need
        to be adjusted by 1) transforming their coordinates to lat/lon BEFORE
        the map is redrawn, 2) redrawing the map, 3) transforming the stored
        lat/lon coordinates to the new map coordinates.
        """
        # Convert the current axis corners to lat/lon coordinates.
        axis = self.ax.axis()
        self.kwargs['llcrnrlon'], self.kwargs['llcrnrlat'] = \
                                  self.__call__(axis[0], axis[2], inverse=True)
        self.kwargs['urcrnrlon'], self.kwargs['urcrnrlat'] = \
                                  self.__call__(axis[1], axis[3], inverse=True)

        logging.debug("corner coordinates (lat/lon): ll(%.2f,%.2f), "\
                      "ur(%.2f,%.2f)" % (self.kwargs['llcrnrlat'],
                                         self.kwargs['llcrnrlon'],
                                         self.kwargs['urcrnrlat'],
                                         self.kwargs['urcrnrlon']))

        if self.kwargs["projection"] in ["cyl"]:
            # Latitudes in cylindrical projection need to be within -90..90.
            if self.kwargs['urcrnrlat'] > 90: self.kwargs['urcrnrlat'] = 90
            if self.kwargs['llcrnrlat'] < -90: self.kwargs['llcrnrlat'] = -90
            # Longitudes in cylindrical projection need to be within -360..360.
            if self.kwargs['llcrnrlon'] < -360 \
                   or self.kwargs['urcrnrlon'] < -360:
                self.kwargs['llcrnrlon'] += 360.
                self.kwargs['urcrnrlon'] += 360.
            if self.kwargs['llcrnrlon'] > 360 \
                   or self.kwargs['urcrnrlon'] > 360:
                self.kwargs['llcrnrlon'] -= 360.
                self.kwargs['urcrnrlon'] -= 360.

        # Remove the current map artists.
        grat_vis = self.appearance["draw_graticule"]
        self.set_graticule_visible(False)
        self.appearance["draw_graticule"] = grat_vis
        if self.map_coastlines:
            self.map_coastlines.remove()

        if self.image:
            self.image.remove()
            self.image = None

        # Refer to Basemap.drawcountries() on how to remove country borders.
        # In addition to the matplotlib lines, the loaded country segment data
        # needs to be loaded. THE SAME NEEDS TO BE DONE WITH RIVERS ETC.
        if self.map_countries:
            self.map_countries.remove()
            del self.cntrysegs

        # map_boundary is None for rectangular projections (basemap simply sets
        # the backgorund colour).
        if self.map_boundary:
            try:
                #FIX (mr, 15Oct2012) -- something seems to have changed in
                # newer Matplotlib versions: this causes an exception when
                # the user zooms/pans..
                self.map_boundary.remove()
            except:
                pass

        cont_vis = self.appearance["fill_continents"]
        self.set_fillcontinents_visible(False)
        self.appearance["fill_continents"] = cont_vis

        # POSSIBILITY A): Call self.__init__ again with stored keywords.
        # Update kwargs if new parameters such as the map region have been
        # given.
        if kwargs_update:
            self.kwargs.update(kwargs_update)
        self.__init__(**self.kwargs)

        self.update_trajectory_items()

#TODO: HOW TO MAKE THIS MORE EFFICIENT.
        # POSSIBILITY B): Only set the Basemap parameters that influence the
        # plot (corner lat/lon, x/y, width/height, ..) and re-define the
        # polygons that represent the coastlines etc. In Basemap, they are
        # defined in __init__(), at the very bottom (the code that comes
        # with the comments
        #    >> read in coastline polygons, only keeping those that
        #    >> intersect map boundary polygon.
        # ). Basemap only loads the coastline data that is actually displayed.
        # If we only change llcrnrlon etc. here and replot coastlines etc.,
        # the polygons and the map extent will remain the same.
        # However, it should be possible to make a map change WITHOUT changing
        # coordinates.
        #
        #self.llcrnrlon = llcrnrlon
        #self.llcrnrlat = llcrnrlat
        #self.urcrnrlon = urcrnrlon
        #self.urcrnrlat = urcrnrlat
        #self.llcrnrx = axis[0]
        #self.llcrnry = axis[2]
        #self.urcrnrx = axis[1]
        #self.urcrnry = axis[3]


    def imshow(self, X, **kwargs):
        """Overloads basemap.imshow(). Deletes any existing image and
           redraws the figure after the new image has been plotted.
        """
        if self.image:
            self.image.remove()
        self.image = super(MapCanvas, self).imshow(X, **kwargs)
        self.ax.figure.canvas.draw()
        return self.image


    def set_trajectory_tree(self, tree):
        """Set a reference to the tree data structure containing the information
           about the elements plotted on the map (e.g. flight tracks,
           trajectories).
        """
        logging.debug("registering trajectory tree model")
        # Disconnect old tree, if defined.
        if self.traj_item_tree:
            self.traj_item_tree.disconnect(
                self.traj_item_tree,
                QtCore.SIGNAL("dataChanged(QModelIndex, QModelIndex)"),
                self.update_from_trajectory_tree)
        # Set and connect new tree.
        self.traj_item_tree = tree
        self.traj_item_tree.connect(
            self.traj_item_tree,
            QtCore.SIGNAL("dataChanged(QModelIndex, QModelIndex)"),
            self.update_from_trajectory_tree)
        # Draw tree items.
        self.update_trajectory_items()


    def update_from_trajectory_tree(self, index1, index2):
        """This method should be connected to the 'dataChanged()' signal
           of the MapItemsTree.

        NOTE: If index1 != index2, the entire tree will be updated (I haven't
              found out so far how to get all the items between the two
              indices).
        """
        if not self.traj_item_tree:
            return
        # Update the map elements if the change that occured in traj_item_tree
        # affected a LagrantoMapItem.
        item = index1.internalPointer()
        item2 = index2.internalPointer()
        if isinstance(item, titree.LagrantoMapItem):
            lastChange = self.traj_item_tree.getLastChange()
            # Update the given item or the entire tree if the two given
            # items are different.
            self.update_trajectory_items(item=item if item == item2 else None,
                                         mode=lastChange)


    def update_trajectory_items(self, item=None, mode="DRAW_EVERYTHING"):
        """Draw or update map elements.

        The map items tree is traversed downward starting at the item
        given as the argument 'item' (i.e. the given item and all its
        children will be processed). Also, the path from the given
        item to the root of the tree will be followed to check if any
        property (visibility, colour) is inherited from a higher level.

        If no item is given, the traverse will start at the root, i.e.
        all items on the map will be drawn or updated.

        Keyword arguments:
        item -- LagrantoMapItem instance from which the traversal should
                be started.
        mode -- string with information on what should be done (draw vs.
                update):
                
                DRAW_EVERYTHING -- draw or redraw all elements on the map.
                FLIGHT_TRACK_ADDED -- draw the flight track represented
                    by 'item' (including markers).
                TRAJECTORY_DIR_ADDED -- draw the trajectory represented
                    by 'item' (including markers).
                MARKER_CHANGE -- markers for the current item (and all items in
                    its subtree) have been changed. Delete the old graphics
                    instances and draw new markers.
                GXPROPERTY_CHANGE -- a graphics property has been changed (e.g.
                    colour). Perform a pylab.setp() call to change the property.
                VISIBILITY_CHANGE -- same action as for GXPROPERTY_CHANGE
        """
        # If no trajectory item tree is defined exit the method.
        if not self.traj_item_tree:
            return

        logging.debug("updating trajectory items on map <%s>, mode %s" % \
                      (self.identifier, mode))

        # If no item is given start at the root of the 'traj_item_tree'.
        if not item:
            item = self.traj_item_tree.getRootItem()
            logging.debug("processing all trajectory items")

        # This method can only operate on LagrantoMapItems -- raise an exception
        # if the argument is not of this type.
        elif not isinstance(item, titree.LagrantoMapItem):
            raise TypeError("This method can only process 'LagrantoMapItem's.")

        # Traverse the tree upward from the current item to the tree root,
        # to check if there are any properties that are inherited from an
        # item node at a higher level to the current item (e.g. an item
        # inherits visibility, colour and timeMarkerInterval from its
        # ancestors).
        #
        # Default values: The item is visible and inherits no other properties.
        parentProperties = {"visible": True,
                            "colour": None,
                            "linestyle": None,
                            "linewidth": None,
                            "timeMarkerInterval": None}
        parent = item.parent() # this would be None if item == rootItem
        while parent:          # loop until root has been reached
            # Set visible to False if one item along the path to the root is
            # found to be set to invisible.
            parentProperties["visible"] = parent.isVisible(self.identifier) \
                                          and parentProperties["visible"]

            # Inherit colour and time marker interval of the highest tree level
            # on which they are set (set the current property to the value
            # encountered on the current level if the property is not None,
            # otherwise keep the old value -- since we're moving upward,
            # the property will eventually have the value of the highest
            # level on which is was not None).
            for propName in ["colour", "linestyle", "linewidth",
                             "timeMarkerInterval"]:
                prop = parent.getGxElementProperty("general", propName)
                parentProperties[propName] = prop if prop \
                                             else parentProperties[propName]

            # Move up one level.
            parent = parent.parent()

            
        # Iterative tree traversal: Put the item and its attributes on a
        # stack.
        itemStack = [(item, parentProperties)]

        # Operate on the items in the stack until the stack is empty.
        while len(itemStack) > 0:

            # Get a new item from the stack.
            item, parentProperties = itemStack.pop()

            # Its visibility is determined by its own visibility status
            # and that of its parent (i.e. the subtree it is part of).
            itemProperties = {}
            itemProperties["visible"] = item.isVisible(self.identifier) and \
                                        parentProperties["visible"]
            #
            for propName in ["colour", "linestyle", "linewidth", 
                             "timeMarkerInterval"]:
                itemProperties[propName] = parentProperties[propName] \
                                           if parentProperties[propName] \
                                           else item.getGxElementProperty("general",
                                                                          propName)

            # Push all children of the current item onto the stack that are
            # instances of LagrantoMapItem (VariableItems are not plotted on
            # the map).
            itemStack.extend([(child, itemProperties) for child in item.childItems \
                              if isinstance(child, titree.LagrantoMapItem)])

            # Plotting and graphics property update operations can only be
            # performed for flight tracks and trajectories.
            if not (isinstance(item, titree.FlightTrackItem) \
                    or isinstance(item, titree.TrajectoryItem)):
                continue

            if mode in ["GXPROPERTY_CHANGE", "VISIBILITY_CHANGE"]:
                # Set the visibility of all graphics elements of the current item
                # to 'itemVisible'.
                # NOTE: We do not have to test if the item is of type
                #   FlightTrackItem or TrajectoryItem, since only these
                #   two classes contain fields other that 'general' in
                #   gxElements.
                for element in item.getGxElements():
                    if element == "general":
                        continue
                    elif element == "lineplot":
                        plt.setp(
                               item.getGxElementProperty(element,
                                                         "instance::%s"%self.identifier),
                               visible = itemProperties["visible"],
                               color = itemProperties["colour"],
                               linestyle = itemProperties["linestyle"],
                               linewidth = itemProperties["linewidth"])
                    elif element == "timemarker":
                        plt.setp(
                               item.getGxElementProperty(element,
                                                         "instance::%s"%self.identifier),
                               visible = itemProperties["visible"],
                               color = itemProperties["colour"])

            elif mode in ["FLIGHT_TRACK_ADDED", "TRAJECTORY_DIR_ADDED",
                          "MARKER_CHANGE", "DRAW_EVERYTHING"]:

                # Convert lat/lon data into map coordinates, plot the item path
                # and set the visibility flag. A handle on the plot is stored
                # via the setplotInstance() method, this allows to later switch
                # on/off the visibility.
                x, y = self.__call__(item.getLonVariable().getVariableData(),
                                     item.getLatVariable().getVariableData())
            
                if mode != "MARKER_CHANGE":
                    # Remove old plot instances.
                    try:
                        instances = item.getGxElementProperty("lineplot",
                                                              "instance::%s"%self.identifier)
                        for instance in instances:
                            instance.remove()
                    except (KeyError, ValueError) as e:
                        pass
                    # Plot new instances.
                    plotInstance = self.plot(x, y,
                                             color = itemProperties["colour"],
                                             visible = itemProperties["visible"],
                                             linestyle = itemProperties["linestyle"],
                                             linewidth = itemProperties["linewidth"])
                    item.setGxElementProperty("lineplot",
                                              "instance::%s"%self.identifier,
                                              plotInstance)
            
                # Get the indexes for the time markers. If no time markers should
                # be drawn, 'None' is returned.
                try:
                    # Try to remove an existing time marker instance from
                    # the plot.
                    oldScatterInstance = item.getGxElementProperty("timemarker",
                                                                   "instance::%s"%self.identifier)
                    plt.setp(oldScatterInstance, visible = False)
                    oldScatterInstance.remove()
                except (KeyError, ValueError) as e:
                    pass
                imarker = item.getTimeMarkerIndexes()
                if imarker != None:
                    scatterInstance = self.scatter(x[imarker], y[imarker],
                        s=20, c=itemProperties["colour"],
                        visible=itemProperties["visible"], linewidth=0)
                    item.setGxElementProperty("timemarker",
                                              "instance::%s"%self.identifier,
                                              scatterInstance)

        # Update the figure canvas.
        self.ax.figure.canvas.draw()


    def gcpoints2(self, lon1, lat1, lon2, lat2, del_s=100., map_coords=True):
        """
        The same as basemap.gcpoints(), but takes a distance interval del_s
        to space the points instead of a number of points.
        """
        # use great circle formula for a perfect sphere.
        gc = pyproj.Geod(a=self.rmajor,b=self.rminor)
        az12,az21,dist = gc.inv(lon1,lat1,lon2,lat2)
        npoints = int((dist+0.5*1000.*del_s)/(1000.*del_s))
        lonlats = gc.npts(lon1,lat1,lon2,lat2,npoints)
        lons = [lon1]; lats = [lat1]
        for lon, lat in lonlats:
            lons.append(lon)
            lats.append(lat)
        lons.append(lon2); lats.append(lat2)
        if map_coords:
            x, y = self(lons, lats)
        else:
            x, y = (lons, lats)
        return x, y


    def gcpoints_path(self, lons, lats, del_s=100., map_coords=True):
        """Same as gcpoints2, but for an entire path, i.e. multiple
           line segments. lons and lats are lists of waypoint coordinates.
        """
        # use great circle formula for a perfect sphere.
        gc = pyproj.Geod(a=self.rmajor,b=self.rminor)
        assert len(lons)==len(lats)
        assert len(lons)>1
        gclons = [lons[0]]; gclats = [lats[0]]
        for i in range(len(lons)-1):
            az12,az21,dist = gc.inv(lons[i],lats[i],lons[i+1],lats[i+1])
            npoints = int((dist+0.5*1000.*del_s)/(1000.*del_s))
#BUG -- weird path in cyl projection on waypoint move
# On some system configurations, the path is wrongly plotted when one
# of the waypoints is moved by the user and the current projection is cylindric.
# The weird thing is that when comparing cyl projection and stereo projection
# (which works), the exact same arguments are passed to gc.npts(). Also, the
# gc is initialised with the exact same a and b. Nevertheless, for the cyl 
# projection, gc.npts() returns lons that connect lon1 and lat2, not lon1 and
# lon2 ... I cannot figure out why, maybe this is an issue in certain versions
# of pyproj?? (mr, 16Oct2012)
            #print lons[i],lats[i],lons[i+1],lats[i+1],npoints
            lonlats = gc.npts(lons[i],lats[i],lons[i+1],lats[i+1],npoints)
            #print lonlats
            for lon, lat in lonlats:
                gclons.append(lon)
                gclats.append(lat)
            gclons.append(lons[i+1]); gclats.append(lats[i+1])
        if map_coords:
            x, y = self(gclons, gclats)
        else:
            x, y = (gclons, gclats)
        return x, y
        

    def drawgreatcircle_path(self, lons, lats, del_s=100., **kwargs):
        """
        """
        x, y = self.gcpoints_path(lons, lats, del_s=del_s)
        return self.plot(x,y,**kwargs)


        

################################################################################
###                     CLASS SatelliteOverpassPatch                         ###
################################################################################

class SatelliteOverpassPatch:
    """Represents a satellite overpass on the top view map (satellite
       track and, if available, swath).
    """
# TODO: Derive this class from some Matplotlib actor class? Or create
#       a new abstract base class for objects that can be drawn on the
#       map -- they all should provide methods remove(), update(),
#       etc. update() should automatically remap the object to new map
#       coordinates.
    def __init__(self, mapcanvas, segment):
        """
        """
        self.map = mapcanvas
        self.segment = segment
        # Filter those time elements that correspond to masked positions -- this
        # way the indexes in self.utc correspond to those in self.sat.
        # np.ma.getmaskarray is necessary as ..mask only returns a scalar
        # "False" if the array contains no masked entries.
        self.utc = segment["utc"][np.where(np.ma.getmaskarray( \
                                              segment["satpos"])[:,0] == False)]
        self.sat = np.ma.compress_rows(segment["satpos"])
        self.sw_l = np.ma.compress_rows(segment["swath_left"])
        self.sw_r = np.ma.compress_rows(segment["swath_right"])
        self.trackline = None
        self.patch = None
        self.texts = []
        self.draw()
        

    def draw(self):
        """Do the actual plotting of the patch.
        """
        # Plot satellite track.
        sat = np.copy(self.sat)
        sat[:,0], sat[:,1] = self.map(sat[:,0], sat[:,1])
        self.trackline = self.map.plot(sat[:,0], sat[:,1],
                                       marker='+', markerfacecolor='g')

        # Plot polygon patch that represents the swath of the sensor.
        sw_l = self.sw_l
        sw_r = self.sw_r
        Path = mpath.Path
        pathdata = [(Path.MOVETO, self.map(sw_l[0,0],sw_l[0,1]))]
        for point in sw_l[1:]:
            pathdata.append((Path.LINETO, self.map(point[0],point[1])))
        for point in sw_r[::-1]:
            pathdata.append((Path.LINETO, self.map(point[0],point[1])))
        codes, verts = zip(*pathdata)
        path = mpl_pi.PathH(verts, codes, map=self.map)
        patch = mpatches.PathPatch(path, facecolor='yellow',
                                   edgecolor='yellow', alpha=0.4)
        self.patch = patch
        self.map.ax.add_patch(patch)

        # Draw text labels.
        self.texts.append(self.map.ax.text(sat[0,0], sat[0,1],
                                           self.utc[0].strftime("%H:%M:%S"),
                                           bbox=dict(facecolor='white',
                                                     alpha=0.5,
                                                     edgecolor='none')))
        self.texts.append(self.map.ax.text(sat[-1,0], sat[-1,1],
                                           self.utc[-1].strftime("%H:%M:%S"),
                                           bbox=dict(facecolor='white',
                                                     alpha=0.5,
                                                     edgecolor='none')))
        
        self.map.ax.figure.canvas.draw()


    def update(self):
        """Removes the current plot of the patch and redraws the patch.
           This is necessary, for instance, when the map projection and/or
           extent has been changed.
        """
        self.remove()
        self.draw()


    def remove(self):
        """Remove this satellite patch from the map canvas.
        """
        if self.trackline:
            for element in self.trackline:
                element.remove()
            self.trackline = None
        if self.patch:
            self.patch.remove()
            self.patch = None
        for element in self.texts:
            # Removal of text elements sometimes fails. I don't know why,
            # the plots look fine nevertheless.
            try:
                element.remove()
            except:
                pass