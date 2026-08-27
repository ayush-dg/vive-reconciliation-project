'use client';

import { useActionState } from 'react';
import { useFormStatus } from 'react-dom';
import { loginAction, type LoginState } from './actions';

const initialState: LoginState = { error: null };

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} data-testid="sign-in-submit">
      {pending ? 'Signing in…' : 'Sign in'}
    </button>
  );
}

export default function LoginForm() {
  const [state, formAction] = useActionState(loginAction, initialState);

  return (
    <form action={formAction} noValidate={false}>
      <div>
        <label htmlFor="username">Username/Email</label>
        <input id="username" name="username" type="text" required title="Enter your username" />
      </div>
      <div>
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" required title="Enter your password" />
      </div>

      {state.error && (
        <p role="alert" data-testid="sign-in-error">
          {state.error}
        </p>
      )}

      <SubmitButton />

      <button type="button" disabled title="Coming soon" data-testid="sso-button">
        Sign in with company SSO
      </button>
    </form>
  );
}
