import { useEffect, useState } from 'react';
import { Download, FileText, RefreshCw, Upload } from 'lucide-react';
import { api, DataSourceInventory } from '../data/api';
import { ADMIN_PASSWORD } from '../auth';

export default function DataManagementPanel() {
  const [dataSources, setDataSources] = useState<DataSourceInventory | null>(null);
  const [uploads, setUploads] = useState<any[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  const reload = async () => {
    setLoading(true);
    setError('');
    try {
      const [sources, history] = await Promise.all([
        api.adminListDataSources(),
        api.adminListUploads(ADMIN_PASSWORD),
      ]);
      setDataSources(sources);
      if (Array.isArray(history)) setUploads(history);
    } catch (err: any) {
      setError(err.message || 'Could not read the configured data source.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []);

  const upload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    setError('');
    setResult(null);
    try {
      const response = await api.adminUpload(selectedFile, ADMIN_PASSWORD, 'Auto-matched by name');
      setResult(response);
      setSelectedFile(null);
      await reload();
    } catch (err: any) {
      setError(err.message || 'Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  const choose = (file: File | undefined) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv') && !file.name.toLowerCase().endsWith('.tsv')) {
      setError('Please choose a CSV or TSV file.');
      return;
    }
    setError('');
    setResult(null);
    setSelectedFile(file);
  };

  return <div className="mx-auto max-w-6xl">
    <div className="mb-6"><p className="text-[10px] font-bold uppercase tracking-[0.18em] text-accent-shamrock">Compass control room</p><h1 className="mt-1 text-2xl font-semibold text-gray-900">Compass Backstage</h1><p className="mt-1 text-sm text-gray-500">Keep the right people on course—and peek at who’s stopping by.</p></div>
    <p className="mb-4 rounded-lg bg-zd-green-50 px-3 py-2 text-[10px] leading-relaxed text-gray-600"><span className="font-semibold text-accent-fern">Upload-backed snapshot mode:</span> the dashboard and Ask Compass read the matching uploaded source files. AppFoundry does not use live Salesforce, Snowflake, or Gong fallbacks in this mode. Account Landscape/Bullseye uses <code>account_landscape_current.csv</code>.</p>
    <section className="rounded-xl border border-gray-100 bg-white p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><FileText className="h-4 w-4 text-accent-shamrock" /><div><h2 className="text-sm font-semibold text-gray-900">Source data folder</h2><p className="text-xs text-gray-500">These are the files Compass currently reads.</p></div></div><button type="button" onClick={reload} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-[10px] font-semibold text-gray-600 disabled:opacity-50"><RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />Refresh</button></div>
      {dataSources && <div className="mb-4 rounded-lg bg-zd-green-50 px-3 py-2 text-[10px] text-gray-600"><p><span className="font-semibold text-accent-fern">Folder:</span> {dataSources.directory}</p><p><span className="font-semibold text-accent-fern">Mode:</span> Uploaded snapshot — {dataSources.source_as_of ? `latest update ${new Date(dataSources.source_as_of).toLocaleString()}` : 'no source files found'}</p>{dataSources.missing_files?.length ? <p className="mt-1 text-amber-700"><span className="font-semibold">Still needed:</span> {dataSources.missing_files.join(', ')}</p> : <p className="mt-1 font-semibold text-accent-fern">All required dashboard source files are present.</p>}</div>}
      {dataSources?.files.length ? <div className="space-y-2">{dataSources.files.map((file) => <div key={file.filename} className="flex items-center justify-between gap-3 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2"><div className="min-w-0"><p className="truncate text-[10px] font-semibold text-gray-700">{file.filename}</p><p className="text-[9px] text-gray-400">{file.purpose} · {(file.size_bytes / 1024).toFixed(1)} KB</p></div>{file.downloadable && <a href={`/api/admin/data-download/${encodeURIComponent(file.filename)}`} download className="inline-flex shrink-0 items-center gap-1 rounded-md border border-gray-200 bg-white px-2 py-1.5 text-[10px] font-semibold text-gray-600"><Download className="h-3 w-3" />Download</a>}</div>)}</div> : <p className="rounded-lg bg-gray-50 px-3 py-4 text-center text-[10px] text-gray-400">No files found in the configured data folder.</p>}
    </section>
    <section className="mt-4 rounded-xl border border-gray-100 bg-white p-5 shadow-card"><div className="mb-4 flex items-center gap-2"><Upload className="h-4 w-4 text-accent-shamrock" /><div><h2 className="text-sm font-semibold text-gray-900">Upload data file</h2><p className="text-xs text-gray-500">Upload one verified source extract at a time. Matching filenames are saved to the source folder and used by the whole dashboard after reload.</p></div></div><div className="mb-4 rounded-lg bg-zd-green-50 px-3 py-2 text-[10px] leading-relaxed text-gray-600"><span className="font-semibold text-accent-fern">Accepted source filenames:</span> <code>account_landscape_current.csv</code>, <code>workday_hierarchy_chris_donato.csv</code>, <code>clari_forecast_current_quarter.csv</code>, <code>gtmsi_pipeline_current_quarter.csv</code>, and <code>salesforce_opportunities_current_quarter.csv</code>.</div><div className={`rounded-xl border-2 border-dashed p-6 text-center ${dragOver ? 'border-accent-shamrock bg-zd-green-50' : 'border-gray-200 bg-gray-50/50'}`} onDragOver={(event) => { event.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={(event) => { event.preventDefault(); setDragOver(false); choose(event.dataTransfer.files?.[0]); }}><p className="text-xs font-medium text-gray-700">{uploading ? 'Uploading and matching…' : selectedFile ? 'File ready to upload' : 'Drop a CSV or TSV here'}</p><div className="mt-3 flex justify-center gap-2"><label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700"><FileText className="h-3.5 w-3.5 text-accent-shamrock" />{selectedFile ? 'Change file' : 'Choose file'}<input type="file" accept=".csv,.tsv" className="hidden" disabled={uploading} onChange={(event) => { choose(event.target.files?.[0]); event.target.value = ''; }} /></label><button type="button" onClick={upload} disabled={!selectedFile || uploading} className="inline-flex items-center gap-2 rounded-lg bg-accent-shamrock px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"><Upload className="h-3.5 w-3.5" />{uploading ? 'Uploading…' : 'Upload file'}</button></div>{selectedFile && <p className="mt-3 text-xs text-gray-600">{selectedFile.name}</p>}</div>{result && <p className="mt-3 rounded-lg bg-zd-green-50 px-3 py-2 text-xs text-accent-fern">Uploaded {result.filename} · {result.rows?.toLocaleString() || 0} rows · {result.saved_to_source ? `saved as ${result.saved_to_source}` : 'kept in upload history only'}</p>}{error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}<div className="mt-5"><div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold text-gray-700">Upload history</h3><span className="text-[10px] text-gray-400">{uploads.length} file{uploads.length === 1 ? '' : 's'}</span></div>{uploads.length ? <div className="space-y-2">{uploads.slice(0, 10).map((item) => <div key={item.id} className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2"><p className="truncate text-[10px] font-semibold text-gray-700">{item.filename}</p><span className="text-[10px] text-gray-500">{item.row_count?.toLocaleString() || 0} rows</span></div>)}</div> : <p className="rounded-lg bg-gray-50 px-3 py-4 text-center text-[10px] text-gray-400">No files uploaded yet.</p>}</div></section>
  </div>;
}
