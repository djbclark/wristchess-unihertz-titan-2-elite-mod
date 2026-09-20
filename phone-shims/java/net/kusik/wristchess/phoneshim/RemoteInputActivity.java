package net.kusik.wristchess.phoneshim;

import android.app.Activity;
import android.app.RemoteInput;
import android.content.Intent;
import android.os.Bundle;
import android.os.Parcelable;
import android.text.InputType;
import android.view.Gravity;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;

/**
 * Phone replacement for the Wear OS RemoteInput activity.
 *
 * Wrist Chess collects the Lichess API token with
 * androidx.wear.input.RemoteInputIntentHelper: it starts an implicit intent
 * with action android.support.wearable.input.action.REMOTE_INPUT carrying a
 * RemoteInput[] under EXTRA_REMOTE_INPUTS, and reads the answer back either
 * from the string extra "result_text" or via RemoteInput.getResultsFromIntent()
 * under the RemoteInput's result key ("result"). Phones have no handler for
 * that action, so the app crashed with ActivityNotFoundException. This activity
 * (declared in the manifest by wristchess_phone_build.py) shows one text field
 * per RemoteInput and returns the result both ways.
 */
public final class RemoteInputActivity extends Activity {
    private static final String EXTRA_REMOTE_INPUTS = "android.support.wearable.input.extra.REMOTE_INPUTS";
    private static final String EXTRA_INPUT_ACTION_TYPE = "android.support.wearable.input.extra.INPUT_ACTION_TYPE";
    private static final String EXTRA_RESULT_TEXT = "result_text";

    private RemoteInput[] remoteInputs;
    private EditText[] fields;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        ArrayList<RemoteInput> inputs = new ArrayList<>();
        Parcelable[] parcelables = getIntent().getParcelableArrayExtra(EXTRA_REMOTE_INPUTS);
        if (parcelables != null) {
            for (Parcelable p : parcelables) {
                if (p instanceof RemoteInput) {
                    inputs.add((RemoteInput) p);
                }
            }
        }
        if (inputs.isEmpty()) {
            // No RemoteInput[] (e.g. launched from `adb shell am start -a ...` for a
            // smoke test): still show one generic field so the flow is observable.
            inputs.add(new RemoteInput.Builder("result").setLabel("Input").build());
        }
        remoteInputs = inputs.toArray(new RemoteInput[0]);
        fields = new EditText[remoteInputs.length];

        float density = getResources().getDisplayMetrics().density;
        int pad = (int) (20 * density);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad / 2);

        for (int i = 0; i < remoteInputs.length; i++) {
            RemoteInput ri = remoteInputs[i];
            TextView label = new TextView(this);
            label.setText(ri.getLabel());
            label.setTextSize(18);
            root.addView(label);

            EditText field = new EditText(this);
            field.setSingleLine(true);
            // Visible-password variation: no autocorrect/suggestions for a token.
            field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
            field.setImeOptions(imeAction(ri));
            field.setOnEditorActionListener((v, actionId, event) -> {
                submit();
                return true;
            });
            root.addView(field);
            fields[i] = field;
        }

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setGravity(Gravity.END);
        Button cancel = new Button(this, null, android.R.attr.buttonBarButtonStyle);
        cancel.setText(android.R.string.cancel);
        cancel.setOnClickListener(v -> {
            setResult(RESULT_CANCELED);
            finish();
        });
        Button ok = new Button(this, null, android.R.attr.buttonBarButtonStyle);
        ok.setText(android.R.string.ok);
        ok.setOnClickListener(v -> submit());
        buttons.addView(cancel);
        buttons.addView(ok);
        root.addView(buttons);

        setContentView(root);
        fields[0].requestFocus();
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE);
    }

    /** Maps the wearable INPUT_ACTION_TYPE extra (SEND=0, SEARCH=1, DONE=2, GO=3) to an IME action. */
    private static int imeAction(RemoteInput ri) {
        Bundle extras = ri.getExtras();
        int type = extras != null ? extras.getInt(EXTRA_INPUT_ACTION_TYPE, 0) : 0;
        switch (type) {
            case 1: return EditorInfo.IME_ACTION_SEARCH;
            case 2: return EditorInfo.IME_ACTION_DONE;
            case 3: return EditorInfo.IME_ACTION_GO;
            default: return EditorInfo.IME_ACTION_SEND;
        }
    }

    private void submit() {
        Bundle results = new Bundle();
        for (int i = 0; i < remoteInputs.length; i++) {
            results.putCharSequence(remoteInputs[i].getResultKey(), fields[i].getText().toString());
        }
        Intent data = new Intent();
        RemoteInput.addResultsToIntent(remoteInputs, data, results);
        data.putExtra(EXTRA_RESULT_TEXT, fields[0].getText().toString());
        setResult(RESULT_OK, data);
        finish();
    }
}
