import { api, type Feature } from "./client";

/**
 * Apply multiple feature changes. Uses the batch endpoint when
 * available; falls back to individual POSTs otherwise.
 */
export async function applyFeatureBatch(
  features: Array<Partial<Feature> & { name: string }>,
): Promise<{ applied: number; ok: boolean }> {
  if (features.length === 0) return { applied: 0, ok: true };

  try {
    const res = await api.batchFeatures(features);
    if (res.ok) return { applied: features.length, ok: true };
  } catch {
    /* fall through to per-feature upserts */
  }

  let applied = 0;
  for (const feature of features) {
    await api.upsertFeature(feature);
    applied += 1;
  }
  return { applied, ok: true };
}