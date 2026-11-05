package com.media.oniplayer

import android.content.Intent
import android.os.Bundle
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import com.google.android.material.button.MaterialButton

class WelcomeActivity : AppCompatActivity() {

    private data class GuideItem(
        val iconRes: Int,
        val title: String,
        val description: String
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_YES)
        super.onCreate(savedInstanceState)

        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        if (prefs.getBoolean(KEY_WELCOME_SEEN, false)) {
            openMainActivity()
            return
        }

        setContentView(R.layout.activity_welcome)
        populateGuide()

        findViewById<MaterialButton>(R.id.btnWelcomeGetStarted).setOnClickListener {
            prefs.edit().putBoolean(KEY_WELCOME_SEEN, true).apply()
            openMainActivity()
        }
    }

    private fun openMainActivity() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun populateGuide() {
        populate(
            R.id.gestureControlsContainer,
            listOf(
                GuideItem(R.drawable.ic_brightness, "Brightness", "Swipe up or down on the left side of the screen to adjust brightness."),
                GuideItem(R.drawable.ic_volume_up, "Volume", "Swipe up or down on the right side to adjust system and player volume."),
                GuideItem(R.drawable.ic_gesture_seek, "Precise seek", "Swipe left or right to scrub or seek through the video and preview the target time."),
                GuideItem(R.drawable.ic_gesture_pinch, "Zoom video", "Use a two-finger pinch to zoom in or out of the video."),
                GuideItem(R.drawable.ic_lock, "Lock controls", "Long-press to lock controls; press the lock icon or long-press to unlock.")
            )
        )
    }

    private fun populate(containerId: Int, items: List<GuideItem>) {
        val container = findViewById<LinearLayout>(containerId)
        items.forEach { item ->
            val view = layoutInflater.inflate(R.layout.item_welcome_guide, container, false)
            val icon = view.findViewById<ImageView>(R.id.welcomeItemIcon)
            icon.setImageResource(item.iconRes)
            icon.contentDescription = item.title
            view.findViewById<TextView>(R.id.welcomeItemTitle).text = item.title
            view.findViewById<TextView>(R.id.welcomeItemDescription).text = item.description
            container.addView(view)
        }
    }

    companion object {
        private const val PREFS_NAME = "OniPlayerPrefs"
        private const val KEY_WELCOME_SEEN = "welcome_seen"
    }
}
