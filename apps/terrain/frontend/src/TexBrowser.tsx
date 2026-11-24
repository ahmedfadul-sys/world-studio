import { useEffect, useState } from "react";
import { texCache, texFetch, texFileUrl, texProviders, texSearch, type TexHit, type TexProvider, type TexRecord } from "./api";

/** متصفّح خامات CC0 بدقة 1K (Poly Haven، ambientCG). يعيد مرجعاً قابلاً للنقل `cc0:<مصدر>/<معرّف>` عند الاختيار. */
export default function TexBrowser({ current, onPick }: { current: string | null; onPick: (rec: TexRecord) => void }) {
  const [provs, setProvs] = useState<TexProvider[]>([]);
  const [prov, setProv] = useState("polyhaven");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<TexHit[] | null>(null);
  const [cache, setCache] = useState<TexRecord[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { texProviders().then(setProvs).catch(() => undefined); texCache().then(setCache).catch(() => undefined); }, []);
  const search = async () => { setErr(null); setBusy("search"); try { setHits(await texSearch(prov, q)); } catch (e) { setErr(String((e as Error).message)); setHits(null); } setBusy(null); };
  const pick = async (provider: string, id: string) => {
    setErr(null); setBusy(`${provider}/${id}`);
    try { const r = await texFetch(provider, id); setCache(await texCache()); onPick({ ...r, ref: r.ref ?? `cc0:${r.provider}/${r.id}` }); } catch (e) { setErr(String((e as Error).message)); }
    setBusy(null);
  };
  const credit = provs.find((p) => p.id === prov)?.credit;

  return (
    <div className="texbrowser">
      <h3>خامات مفتوحة CC0 (دقة 1K)</h3>
      <div className="row">
        <select value={prov} onChange={(e) => { setProv(e.target.value); setHits(null); }} aria-label="المصدر">
          {(provs.length ? provs : [{ id: "polyhaven", title: "Poly Haven" }, { id: "ambientcg", title: "ambientCG" }]).map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}</select>
        <input dir="ltr" placeholder="rock, grass, sand…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
        <button onClick={search} disabled={busy === "search"}>{busy === "search" ? "…" : "بحث"}</button>
      </div>
      {err && <div className="msg error">{err}</div>}
      {hits && !hits.length && <p className="hint">لا نتائج.</p>}
      {hits && <div className="texgrid">{hits.map((h) => (
        <button key={h.provider + h.id} className="texcard" disabled={busy !== null} onClick={() => pick(h.provider, h.id)} title={h.categories.join(" · ")}>
          {h.thumb ? <img src={h.thumb} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span className="noimg">▦</span>}
          <span dir="ltr">{h.name}</span>{busy === `${h.provider}/${h.id}` && <em>جارٍ التنزيل…</em>}
        </button>))}</div>}
      {cache.length > 0 && <>
        <h3>المنزَّلة محلياً</h3>
        <div className="texgrid">{cache.map((r) => (
          <button key={r.ref} className={"texcard" + (current === r.ref ? " on" : "")} onClick={() => onPick(r)} title={`${r.provider}/${r.id}`}>
            <img src={texFileUrl(r)} alt="" loading="lazy" /><span dir="ltr">{r.name}</span></button>))}</div></>}
      <p className="hint">كل الخامات بترخيص CC0 (مجال عام): تُنزَّل بدقة 1K فقط وتُحفظ محلياً وتُنسخ إلى التصدير مع ملف الشكر. {credit}.</p>
    </div>
  );
}
