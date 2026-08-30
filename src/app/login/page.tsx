import Image from 'next/image';
import LoginForm from './LoginForm';

export default function LoginPage() {
  return (
    <div className="login-view">
      <div className="login-card">
        <div className="vc-mark">
          <Image src="/vive-logo.png" alt="Vive Collision" width={90} height={90} priority />
        </div>
        <h2>Sign in to Vive Reconciliation</h2>
        <p className="sub">Use your Vive Collision work account.</p>
        <LoginForm />
        <div className="login-foot">Vive Collision · Insight Factory · Confidential</div>
      </div>
    </div>
  );
}
