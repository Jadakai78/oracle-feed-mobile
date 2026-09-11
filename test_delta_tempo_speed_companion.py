import unittest
import numpy as np
import delta_tempo_speed_companion as companion


def bars(values):
    values = np.asarray(values, dtype=float)
    highs = values + 0.5
    lows = values - 0.5
    opens = values - 0.1
    volumes = np.ones(len(values))
    times = np.arange(len(values))
    return times, highs, lows, values, volumes, volumes


class SpeedCompanionTests(unittest.TestCase):
    def setUp(self):
        companion._STATE.clear()

    def call(self, pair, closes, flow_ratio=1.3, reclaim=False, structure=None, state=None):
        return companion.evaluate(pair, 'LONG', True, 0.8, flow_ratio, reclaim, structure or {'market_condition': 'TRENDING_UP'}, state or {}, bars(closes))

    def test_initial_impulse_is_watch_only(self):
        result = self.call('A', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 102.6, 103.8])
        self.assertEqual(result['episode_state'], 'WATCH_INITIAL_IMPULSE')
        self.assertTrue(result['active_feed_visibility'])
        self.assertFalse(result['entry_authority'])

    def test_pullback_reacceleration_promotes_after_watch(self):
        self.call('B', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 102.6, 103.8])
        self.call('B', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 103.0, 103.2], flow_ratio=1.0)
        result = self.call('B', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 102.0, 105.0], structure={'market_condition': 'PULLBACK_UP'})
        self.assertEqual(result['episode_state'], 'CONFIRMED_PULLBACK_REACCELERATION')

    def test_reclaim_promotes_before_decay(self):
        self.call('C', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 102.6, 103.8])
        result = self.call('C', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 101.6, 104.8], reclaim=True)
        self.assertEqual(result['episode_state'], 'CONFIRMED_RECLAIM_ACCELERATION')

    def test_breakout_acceptance_promotes(self):
        self.call('D', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 102.6, 103.8])
        result = self.call('D', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 102.0, 105.2], structure={'market_condition': 'BREAKOUT_UP', 'bos': True})
        self.assertEqual(result['episode_state'], 'CONFIRMED_BREAKOUT_ACCEPTANCE')

    def test_decay_drops_visibility(self):
        self.call('E', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 103.5, 106.0])
        result = self.call('E', [100, 100.1, 100.2, 100.4, 100.8, 101.5, 105.9, 106.0], flow_ratio=1.0)
        self.assertEqual(result['episode_state'], 'DROPPED')
        self.assertFalse(result['active_feed_visibility'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
