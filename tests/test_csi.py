import unittest
import numpy as np
from pc.csi import HEADER, decode, Preprocessor, sanitize_phase, gaussian_augment, doppler_spectrogram

class CSITests(unittest.TestCase):
    def test_wire(self):
        raw = HEADER.pack(b'CSI1', 1, 1, 3, 9, 1000000, b'123456', -50, 6, 8)
        p = decode(raw + bytes([2,3,4,5,6,7,8,9]))
        self.assertTrue(np.isnan(p.csi[:2]).all())
        self.assertEqual(p.csi[2], 7+6j)
        self.assertEqual(p.timestamp, 1.)
        for bad in (raw, raw + bytes(9), b'bad'):
            with self.assertRaises(ValueError): decode(bad)
    def test_gain(self):
        x = np.arange(1,65)*(1+1j)
        np.testing.assert_allclose(Preprocessor().process(x), Preprocessor().process(x*4), atol=1e-10)
    def test_phase(self):
        k = np.arange(-26,27)
        np.testing.assert_allclose(sanitize_phase(np.exp(1j*(.1*k+.7)), k), 0, atol=1e-10)
    def test_stft(self):
        t = np.arange(512)/100
        x = np.sin(2*np.pi*7.8125*t)
        f, _, db = doppler_spectrogram(t,x)
        self.assertAlmostEqual(f[np.argmax(db.mean(axis=1))], 7.8125)
        t[256:] += 1
        with self.assertRaises(ValueError): doppler_spectrogram(t,x)
    def test_augmentation(self):
        x = np.zeros(10000)
        self.assertAlmostEqual(gaussian_augment(x,.1,42).std(), .1, places=2)
        self.assertTrue(np.all(x==0))
