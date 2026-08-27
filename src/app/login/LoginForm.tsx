'use client';

import { useActionState } from 'react';
import { useFormStatus } from 'react-dom';
import { loginAction, type LoginState } from './actions';

const initialState: LoginState = { error: null };

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary login-submit" disabled={pending} data-testid="sign-in-submit">
      {pending ? 'Signing in…' : 'Sign in'}
    </button>
  );
}

export default function LoginForm() {
  const [state, formAction] = useActionState(loginAction, initialState);

  return (
    <form action={formAction} noValidate={false}>
      <div className="field">
        <label htmlFor="username">Username/Email</label>
        <input id="username" name="username" type="text" required title="Enter your username" />
      </div>
      <div className="field">
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" required title="Enter your password" />
      </div>

      {state.error && (
        <p role="alert" className="sign-in-error" data-testid="sign-in-error">
          {state.error}
        </p>
      )}

      <SubmitButton />

      <div className="divider-text">or continue with</div>

      <button type="button" className="btn btn-sso" disabled title="Coming soon" data-testid="sso-button">
        <svg className="icon" style={{ stroke: 'var(--text-muted)' }}>
          <use href="#i-key" />
        </svg>
        Sign in with company SSO
      </button>
    </form>
  );
}
