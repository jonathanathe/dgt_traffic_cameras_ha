"""Tests de const.py: validación de las constantes de hash.

Cubre M-01 de la auditoría: un hash SHA-256 truncado (63 caracteres en vez
de 64) en PLACEHOLDER_IMAGE_SHA256_HASHES nunca coincidía con nada, sin dar
ningún error visible en ningún sitio.
"""

from __future__ import annotations

import unittest

from ._load import load

const = load("const")


class TestPlaceholderHashes(unittest.TestCase):
    def test_todos_los_hashes_miden_64_caracteres(self) -> None:
        for hash_ in const.PLACEHOLDER_IMAGE_SHA256_HASHES:
            self.assertEqual(
                len(hash_),
                64,
                f"{hash_!r} no mide 64 caracteres (SHA-256 en hexadecimal)",
            )

    def test_todos_los_hashes_son_hexadecimales_en_minusculas(self) -> None:
        for hash_ in const.PLACEHOLDER_IMAGE_SHA256_HASHES:
            self.assertTrue(
                all(c in "0123456789abcdef" for c in hash_),
                f"{hash_!r} contiene caracteres fuera de 0-9a-f",
            )

    def test_validar_hashes_rechaza_uno_truncado(self) -> None:
        with self.assertRaises(ValueError):
            const._validar_hashes_sha256(frozenset({"a" * 63}))

    def test_validar_hashes_rechaza_mayusculas(self) -> None:
        with self.assertRaises(ValueError):
            const._validar_hashes_sha256(frozenset({"A" * 64}))

    def test_validar_hashes_acepta_uno_correcto(self) -> None:
        # No debe lanzar nada.
        const._validar_hashes_sha256(frozenset({"a" * 64}))


if __name__ == "__main__":
    unittest.main()
