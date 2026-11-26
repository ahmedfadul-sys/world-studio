import { useEffect, useRef, useState } from "react";
import { benchStart, benchStatus, type BenchJob } from "./api";
import type { Project } from "./types";

/** صفحة قياس الأداء: تشغّل مشروعاً قياسياً ثابتاً أو مشروعك الحالي على جهازك وتعرض الأزمنة وتقدير تصدير العالم كاملاً. */
export default function PerfBench({ project, onClose }: { project: Project; onClose: () => void }) {
  const [job, setJob] = useState<BenchJob | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearInterval(timer.current), []);
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);

  const run = async (current: boolean) => {
    setErr(null); setJob(null);
    try {
      const id = await benchStart(current ? project : null);
      window.clearInterval(timer.current);
      timer.current = window.setInterval(async () => {
        const j = await benchStatus(id).catch(() => null);
        if (!j) return;
        setJob(j);
        if (j.state !== "running") window.clearInterval(timer.current);
      }, 1500);
    } catch (e) { setErr(String((e as Error).message || e)); }
  };
  const running = job?.state === "running";
  const fmt = (s: number) => (s >= 60 ? `${Math.floor(s / 60)} د ${Math.round(s % 60)} ث` : `${s.toFixed(2)} ث`);
  const m = job?.machine;
  return (
    <div className="modal3d center" role="dialog" aria-modal="true" aria-label="قياس الأداء" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bench">
        <div className="bench-h"><b>قياس الأداء</b><button className="ghost" aria-label="إغلاق" onClick={onClose}>✕</button></div>
        <p className="hint">يقيس سرعة الحساب على جهازك. يعمل في الخلفية دون تغيير مشروعك، ويستغرق من دقيقة إلى بضع دقائق حسب الجهاز. لا تشغّل تصديراً أثناءه.</p>
        <div className="row">
          <button className="primary" disabled={running} onClick={() => run(false)}>مشروع قياسي (20 كم)</button>
          <button disabled={running} onClick={() => run(true)}>مشروعي الحالي</button>
        </div>
        {err && <div className="msg error">{err}</div>}
        {job && <>
          {running && <progress value={job.done} max={job.total} style={{ width: "100%" }} />}
          {job.state === "error" && <div className="msg error">{job.error}</div>}
          <table className="bench-t"><tbody>
            {job.steps.map((s, i) => <tr key={i}><td>{s.label}{s.note && <small> · {s.note}</small>}</td><td dir="ltr">{fmt(s.seconds)}</td><td dir="ltr">{s.mem_mb ? `${s.mem_mb} MB` : ""}</td></tr>)}
          </tbody></table>
          {job.estimate && <div className="msg warn">تصدير العالم كاملاً: <b>{job.estimate.tiles} مربع</b> × {fmt(job.estimate.seconds_per_tile)} ≈ <b>{job.estimate.total_minutes >= 90 ? `${(job.estimate.total_minutes / 60).toFixed(1)} ساعة` : `${job.estimate.total_minutes} دقيقة`}</b>
            <br /><small>{job.estimate.note}</small></div>}
          {m && <p className="hint" dir="ltr">CPU {m.cpu_count} · RAM {m.ram_gb ?? "?"} GB · Python {m.python} · NumPy {m.numpy}{m.scipy ? ` · SciPy ${m.scipy}` : ""}</p>}
        </>}
      </div>
    </div>
  );
}
