import { useEffect, useState, type ReactNode } from 'react';

export function DemoGate({children}: {children: ReactNode}) {
  const [ready, setReady] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fetch('/demo-session').then(async r => {
      if (r.ok) setReady(true);
      else if (r.status !== 401) setError((await r.json()).error || 'Demo unavailable.');
    }).catch(() => setError('Unable to reach the demo. Please retry.'));
  }, []);
  if (ready) return children;
  return <main className="demo-gate"><span className="eyebrow">NSE · PRIVATE DEMO</span><h1>Follow the evidence.</h1>
    <p>Enter the demo code shared by the presenter.</p>
    <form onSubmit={async event => {event.preventDefault();setBusy(true);setError('');
      try { const r = await fetch('/demo-session', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code})});
        if (r.ok) {setCode('');setReady(true);} else setError((await r.json()).error || 'Unable to sign in.');
      } catch {setError('Unable to reach the demo. Please retry.');} finally {setBusy(false);}
    }}><label htmlFor="demo-code">Demo code</label><input id="demo-code" type="password" value={code} onChange={e => setCode(e.target.value)} autoComplete="current-password" required disabled={busy}/><button type="submit" disabled={busy || !code.trim()}>{busy ? 'Connecting…' : 'Open demo →'}</button></form>
    {error && <p className="inline-error" role="alert">{error}</p>}
    <small>Live retrieval runs on the presenter’s PC. The host needs to be online.</small>
  </main>;
}
