"""アプリが使う見本（ユーザーのデータフォルダの複製）を、同梱の見本の更新に追従させる。

アプリはインストール先に書き込めないため、同梱の見本（app/ocr/templates）を
%LOCALAPPDATA%\\QuriousCraftingLog\\ocr_templates に複製して使い、ラベル入力で付けた見本もそこに追記する。
そのため、見本の各ファイル（{解像度}_{種類}.npz/.json）は「複製したときの同梱の見本」の後ろに
「ユーザーが付けた見本」が並んだ形になっている。

アプリの更新で同梱の見本が変わっていたら（増えた・減った・ラベルを直した）、次のように組み直す:
  1. 新しい同梱の見本をすべて入れる（開発側でラベルを直した場合も、それが反映される）
  2. ユーザーが付けた見本のうち、同梱の見本と同じもの（照合で一致するもの）以外を後ろに足す
複製したときの同梱の見本の数と内容の要約（fingerprints）は bundled_manifest.json に記録しておく。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

from app.ocr.kuijin_ocr import KIND_SHAPE, MATCH_THRESHOLD, SKILL_PROPS_FILE, block_distance, iou_distance

MANIFEST_FILE = "bundled_manifest.json"


def _kind_of(stem: str) -> str:
    """"1280x720_slot_base3" -> "slot"、"1280x720_money_glyph" -> "money_glyph"。"""
    kind = stem.split("_", 1)[1]
    return "slot" if kind.startswith("slot_base") else kind


def _load_bank(directory: Path, stem: str) -> tuple[np.ndarray, list]:
    bits = np.load(directory / f"{stem}.npz")["bits"]
    labels = json.loads((directory / f"{stem}.json").read_text(encoding="utf-8"))
    return bits, labels


def _save_bank(directory: Path, stem: str, bits: np.ndarray, labels: list) -> None:
    np.savez_compressed(directory / f"{stem}.npz", bits=bits)
    (directory / f"{stem}.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")


def _matches_any(bank_bits: np.ndarray, bits: np.ndarray, kind: str) -> bool:
    """bits が bank_bits のどれかと、読み取りの照合（TemplateBank.match）の条件で一致するか。"""
    if not len(bank_bits):
        return False
    whole, block = MATCH_THRESHOLD.get(kind, MATCH_THRESHOLD["default"])
    dist = iou_distance(bank_bits, bits)
    dist = np.where(block_distance(bank_bits, bits, KIND_SHAPE[kind]) < block, dist, 1.0)
    return bool(dist.min() < whole)


def _bundled_stems(bundled: Path) -> list[str]:
    return sorted(p.stem for p in bundled.glob("*.json") if (bundled / f"{p.stem}.npz").exists())


FINGERPRINTS_KEY = "fingerprints"   # manifest の中の、同梱の見本の内容の要約（{ファイル名: 要約}）


def _fingerprint(bits: np.ndarray, labels: list) -> str:
    """見本の内容（形とラベル）の要約。同梱の見本が前回の複製から変わったかを調べるのに使う。"""
    digest = hashlib.sha256(np.packbits(bits).tobytes())
    digest.update(json.dumps([list(bits.shape), labels], ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def _write_manifest(user: Path, bundled: Path) -> None:
    banks = {stem: _load_bank(bundled, stem) for stem in _bundled_stems(bundled)}
    manifest: dict = {stem: len(labels) for stem, (_, labels) in banks.items()}
    manifest[FINGERPRINTS_KEY] = {stem: _fingerprint(bits, labels) for stem, (bits, labels) in banks.items()}
    (user / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


def _common_prefix(a: np.ndarray, b: np.ndarray) -> int:
    n = 0
    while n < min(len(a), len(b)) and np.array_equal(a[n], b[n]):
        n += 1
    return n


def sync_templates(user: Path, bundled: Path) -> list[str]:
    """user（複製）を bundled（同梱）の更新に追従させる。変更した見本のファイル名（拡張子なし）を返す。

    user が無ければ bundled を複製する（確認用の拡大画像 review は除く）。
    """
    if not user.exists():
        shutil.copytree(bundled, user, ignore=shutil.ignore_patterns("review"))
        _write_manifest(user, bundled)
        return []

    manifest_path = user / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    changed = []
    for stem in _bundled_stems(bundled):
        new_bits, new_labels = _load_bank(bundled, stem)
        if not (user / f"{stem}.npz").exists():
            _save_bank(user, stem, new_bits, new_labels)   # 同梱に新しくできた種類（新しい初期スロットなど）
            changed.append(stem)
            continue
        user_bits, user_labels = _load_bank(user, stem)
        # 複製したときの同梱の見本の数。記録が無ければ（この仕組みより前の複製）、先頭から同じ見本の数とみなす
        old_count = manifest.get(stem, _common_prefix(user_bits, new_bits))
        # 同梱の見本が、前回複製したときから変わっていなければ何もしない（数だけで比べると、開発側で
        # 見本を外した・ラベルだけ直した場合に反映されない）。要約の記録が無い複製（この仕組みより前）は、
        # 複製の先頭と比べる
        old_fingerprint = manifest.get(FINGERPRINTS_KEY, {}).get(stem)
        if old_fingerprint is not None:
            unchanged = old_fingerprint == _fingerprint(new_bits, new_labels)
        else:
            unchanged = (len(new_labels) == old_count and user_labels[:old_count] == new_labels
                         and np.array_equal(user_bits[:old_count], new_bits))
        if unchanged:
            continue
        kind = _kind_of(stem)
        added_bits = [bits for bits in user_bits[old_count:]]
        added_labels = user_labels[old_count:]
        merged_bits, merged_labels = list(new_bits), list(new_labels)
        for bits, label in zip(added_bits, added_labels):
            if not _matches_any(np.array(merged_bits), bits, kind):
                merged_bits.append(bits)
                merged_labels.append(label)
        _save_bank(user, stem, np.array(merged_bits), merged_labels)
        changed.append(stem)

    # 画面判定の見本は、無いものだけ足す
    for sig in (bundled / "screens").glob("*.png"):
        target = user / "screens" / sig.name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sig, target)

    # スキルの性質（最大レベル・アイコンの色）は、確認済みの同梱の値を優先してまとめる
    bundled_props_path, user_props_path = bundled / SKILL_PROPS_FILE, user / SKILL_PROPS_FILE
    if bundled_props_path.exists():
        bundled_props = json.loads(bundled_props_path.read_text(encoding="utf-8"))
        user_props = json.loads(user_props_path.read_text(encoding="utf-8")) if user_props_path.exists() else {}
        merged_props = {**user_props, **bundled_props}
        if merged_props != user_props:
            user_props_path.write_text(json.dumps(merged_props, ensure_ascii=False, indent=1), encoding="utf-8")

    _write_manifest(user, bundled)
    return changed
