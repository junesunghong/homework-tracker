package kr.home.homeworktracker;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** 재부팅하거나 앱이 업데이트되면, 서버 기기는 서버를 다시 켠다. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String a = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(a) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)) return;
        if (Prefs.isServer(context)) ServerService.start(context);
    }
}
