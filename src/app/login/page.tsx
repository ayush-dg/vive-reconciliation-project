import Image from 'next/image';
import LoginForm from './LoginForm';

export default function LoginPage() {
  return (
    <div className="login-shell">
      <div className="login-hero">
        <div className="login-hero-inner">
          <div className="eyebrow">Vive Collision &nbsp;·&nbsp; AP Operations</div>
          <h1>
            Vendor statements,
            <br />
            <span>reconciled automatically.</span>
          </h1>
          <p>
            Upload a parts vendor statement and get a line-by-line match against NetSuite in
            minutes — exceptions flagged, invoices matched, ready for your review.
          </p>
        </div>
      </div>
      <div className="login-panel">
        <div className="login-card">
          <div className="vc-mark">
            <Image src="/vive-logo.png" alt="Vive Collision" width={72} height={72} />
          </div>
          <h2>Sign in to Vive Reconciliation</h2>
          <p className="sub">Use your Vive Collision work account.</p>
          <LoginForm />
          <div className="login-foot">Vive Collision · Confidential</div>
        </div>
      </div>
    </div>
  );
}
