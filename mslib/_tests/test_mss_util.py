# Copyright: 20016 by ReimarBauer
# License: Apache-2.0, see LICENSE.txt for details.

"""
mslib.mss_util tests
"""

import datetime
from mslib import mss_util


class TestConfigLoader(object):
    """
    tests config file for client
    """
    def test_default_config(self):
        data = mss_util.config_loader()
        assert isinstance(data, dict)
        assert data['WMS_login'] == {'http://localhost:8081': ['mswms', 'forever_forecast_2016']}
        assert data["num_labels"] == 10

    def test_default_config_dataset(self):
        data = mss_util.config_loader(dataset="num_labels")
        assert data == 10
        # defined value and not a default one
        data = mss_util.config_loader(dataset="num_labels", default=5)
        assert data == 10
        # default for non existing entry
        data = mss_util.config_loader(dataset="foobar", default=5)
        assert data == 5

    def test_default_config_wrong_file(self):
        # return default if no access to config file given
        data = mss_util.config_loader(config_file="foo.json", default={"foo": "123"})
        assert data == {"foo": "123"}


class TestGetDistance(object):
    """
    tests for distance based calculations
    """
    # we don't test the utils method here, may be that method should me refactored off
    def test_get_distance(self):
        coordinates_distance = [((50.355136, 7.566077), (50.353968, 4.577915), 212),
                                ((-5.135943, -42.792442), (4.606085, 120.028077), 18130)]
        for coord1, coord2, distance in coordinates_distance:
            assert int(mss_util.get_distance(coord1, coord2)) == distance


class TestTimes(object):
    """
    tests about times
    """
    def test_datetime_to_jsec(self):
        assert mss_util.datetime_to_jsec(datetime.datetime(2000, 2, 1, 0, 0, 0, 0)) == 2678400.0
        assert mss_util.datetime_to_jsec(datetime.datetime(2000, 1, 1, 0, 0, 0, 0)) == 0
        assert mss_util.datetime_to_jsec(datetime.datetime(1995, 1, 1, 0, 0, 0, 0)) == -157766400.0

    def test_jsec_to_datetime(self):
        assert mss_util.jsec_to_datetime(0) == datetime.datetime(2000, 1, 1, 0, 0, 0, 0)
        assert mss_util.jsec_to_datetime(3600) == datetime.datetime(2000, 1, 1, 1, 0, 0, 0)
        assert mss_util.jsec_to_datetime(-157766400.0) == datetime.datetime(1995, 1, 1, 0, 0, 0, 0)

    def test_compute_hour_of_day(self):
        assert mss_util.computeHourOfDay(0) == 0
        assert mss_util.computeHourOfDay(86400) == 0
        assert mss_util.computeHourOfDay(3600) == 1
        assert mss_util.computeHourOfDay(82800) == 23


class TestAngles(object):
    """
    tests about angles
    """
    def test_normalize_angle(self):
        assert mss_util.fix_angle(0) == 0
        assert mss_util.fix_angle(180) == 180
        assert mss_util.fix_angle(270) == 270
        assert mss_util.fix_angle(-90) == 270
        assert mss_util.fix_angle(-180) == 180
        assert mss_util.fix_angle(-181) == 179

    def test_compute_solar_angle(self):
        azimuth_angle, zenith_angle = mss_util.compute_solar_angle(0, 7.56607, 50.355136)
        assert int(azimuth_angle * 1000) == 13510
        assert int(zenith_angle * 1000) == -62205
        azimuth_angle, zenith_angle = mss_util.compute_solar_angle(12, 7.56607, 50.355136)
        assert int(azimuth_angle * 1000) == 13607
        assert int(zenith_angle * 1000) == -62197

    def test_rotate_point(self):
        assert mss_util.rotatePoint([0, 0], 0) == (0.0, 0.0)
        assert mss_util.rotatePoint([0, 0], 180) == (0.0, 0.0)
        assert mss_util.rotatePoint([1, 0], 0) == (1.0, 0.0)
        assert mss_util.rotatePoint([100, 90], 90) == (-90, 100)


class TestConverter(object):
    def test_convert_pressure_to_altitude(self):
        assert mss_util.convertHPAToKM(1013.25) == 0
        assert int(mss_util.convertHPAToKM(25) * 1000) == 22415
