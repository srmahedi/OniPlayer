package com.media.oniplayer

import android.Manifest
import android.content.pm.PackageManager
import android.database.Cursor
import android.os.Bundle
import android.provider.MediaStore
import android.os.Environment
import android.widget.Toast
import android.media.AudioManager
import android.media.MediaScannerConnection
import android.media.MediaMetadataRetriever
import android.util.TypedValue
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.provider.DocumentsContract
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.ActivityInfo
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import org.videolan.libvlc.LibVLC
import org.videolan.libvlc.Media
import org.videolan.libvlc.MediaPlayer
import org.videolan.libvlc.interfaces.IMedia
import org.videolan.libvlc.util.VLCVideoLayout
import java.io.File
import java.util.Locale

class MainActivity : AppCompatActivity() {

    // ── Natural (alphanumeric) sort comparator ─────────────────────────────
    // Splits strings into alternating text/number chunks so that
    // "ch-2" < "ch-10" < "ch-100" instead of lexicographic "ch-10" < "ch-100" < "ch-2".
    private val naturalSortComparator: Comparator<String> = Comparator { a, b ->
        val re = Regex("(\\d+|\\D+)")
        val chunksA = re.findAll(a).map { it.value }.toList()
        val chunksB = re.findAll(b).map { it.value }.toList()
        val len = minOf(chunksA.size, chunksB.size)
        for (i in 0 until len) {
            val ca = chunksA[i]
            val cb = chunksB[i]
            val cmp = if (ca[0].isDigit() && cb[0].isDigit()) {
                ca.toLongOrNull()?.compareTo(cb.toLongOrNull() ?: 0L) ?: ca.compareTo(cb)
            } else {
                ca.lowercase().compareTo(cb.lowercase())
            }
            if (cmp != 0) return@Comparator cmp
        }
        chunksA.size - chunksB.size
    }
    companion object {
        private val SUBTITLE_EXTENSIONS = setOf(
            "srt", "ass", "ssa", "vtt", "sub", "smi", "ttml", "dfxp"
        )
        private val VIDEO_EXTENSIONS = setOf(
            "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "3gp", "ts"
        )
        private const val PREF_ORIGINAL_SYSTEM_VOLUME = "original_system_volume"
    }

    // ── Views ──────────────────────────────────────────────────────────────
    private lateinit var folderRecyclerView: RecyclerView
    private lateinit var videoRecyclerView: RecyclerView
    private lateinit var vlcVideoLayout: VLCVideoLayout
    private lateinit var folderSwipeRefresh: SwipeRefreshLayout
    private lateinit var videoSwipeRefresh: SwipeRefreshLayout
    private lateinit var noVideosLayout: android.widget.LinearLayout
    private lateinit var permissionDeniedLayout: android.widget.LinearLayout
    private lateinit var btnGrantPermission: android.widget.Button

    private lateinit var playerContainer: android.widget.FrameLayout
    private lateinit var playbackControls: android.widget.FrameLayout
    private lateinit var tvVideoTitle: android.widget.TextView
    private lateinit var btnCloseVideo: android.widget.ImageButton
    private lateinit var btnPrevious: android.widget.ImageButton
    private lateinit var btnPlayPause: android.widget.ImageButton
    private lateinit var btnNext: android.widget.ImageButton
    private lateinit var btnContinueFromPosition: android.widget.ImageButton
    private lateinit var tvCurrentTime: android.widget.TextView
    private lateinit var tvTotalTime: android.widget.TextView
    private lateinit var seekBar: android.widget.SeekBar
    private lateinit var btnOrientation: android.widget.ImageButton
    private lateinit var btnAudioTracks: android.widget.ImageButton
    private lateinit var btnSubtitleTracks: android.widget.ImageButton
    private lateinit var topControlsContainer: android.widget.LinearLayout
    private lateinit var bottomControlsContainer: android.widget.LinearLayout
    
    private var topControlsHeight = 0
    private var bottomControlsHeight = 0
    
    // Gesture overlay views
    private lateinit var gestureOverlay: android.widget.LinearLayout
    private lateinit var brightnessIndicator: android.widget.LinearLayout
    private lateinit var volumeIndicator: android.widget.LinearLayout
    private lateinit var seekIndicator: android.widget.FrameLayout
    private lateinit var zoomIndicator: android.widget.LinearLayout
    private lateinit var tvBrightnessPercent: android.widget.TextView
    private lateinit var tvVolumePercent: android.widget.TextView
    private lateinit var tvSeekTime: android.widget.TextView
    private lateinit var tvSeekOffset: android.widget.TextView
    private lateinit var tvZoomPercent: android.widget.TextView
    // ivSeekIcon removed as per user request
    private lateinit var brightnessProgressBar: android.widget.ProgressBar
    private lateinit var volumeProgressBar: android.widget.ProgressBar
    
    private var isControlsVisible = true
    private val hideControlsRunnable = Runnable { playbackControls.visibility = android.view.View.GONE; isControlsVisible = false }
    
    // Lock screen gesture state
    private var isUiLocked = false
    private lateinit var btnLockScreen: android.widget.ImageButton
    private val lockRunnable = Runnable { lockUi() }
    private val unlockRunnable = Runnable { unlockUi() }
    private val hideLockIconRunnable = Runnable { fadeOutLockIcon() }
    private var lastTouchX = 0f
    private var lastTouchY = 0f
    private val TOUCH_SLOP = 30f // pixels

    private val hideGestureOverlayRunnable = Runnable {
        gestureOverlay.animate()
            .alpha(0f)
            .setDuration(150)
            .withEndAction {
                if (!isGesturing) {
                    gestureOverlay.visibility = android.view.View.GONE
                    brightnessIndicator.visibility = android.view.View.INVISIBLE
                    volumeIndicator.visibility = android.view.View.INVISIBLE
                    seekIndicator.visibility = android.view.View.INVISIBLE
                    zoomIndicator.visibility = android.view.View.INVISIBLE
                }
            }
            .start()
    }
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())

    // ── VLC ────────────────────────────────────────────────────────────────
    private var libVLC: LibVLC? = null
    private var mediaPlayer: MediaPlayer? = null
    private lateinit var audioManager: AudioManager
    private lateinit var gestureDetector: android.view.GestureDetector
    private lateinit var scaleGestureDetector: android.view.ScaleGestureDetector

    // ── Data ───────────────────────────────────────────────────────────────
    private var allVideos: MutableList<VideoItem> = mutableListOf()
    private var folders: List<FolderItem> = emptyList()
    private var currentPlaylist: List<VideoItem> = emptyList()
    private var currentPlayingIndex: Int = -1
    private var currentFolderName: String = ""
    private var currentFolderPath: String = ""
    private lateinit var sharedPrefs: SharedPreferences
    
    // Scroll position memory for video lists
    private var savedVideoListScrollPosition: Int = 0

    // Refresh state tracking
    private var isRefreshing = false
    private var refreshCallbackRunnable: Runnable? = null

    // ── State ──────────────────────────────────────────────────────────────
    private enum class Screen { FOLDERS, VIDEOS, PLAYER }
    private var currentScreen = Screen.FOLDERS
    
    // Multi-select state
    private var isMultiSelectMode = false
    private val selectedFolders = mutableSetOf<String>()
    private val selectedVideos = mutableSetOf<String>()
    
    // Multi-select UI components
    private lateinit var multiSelectTitleBar: android.widget.LinearLayout
    private lateinit var btnMultiSelectDelete: com.google.android.material.button.MaterialButton
    private lateinit var btnMultiSelectClose: com.google.android.material.button.MaterialButton
    private lateinit var tvSelectedCount: android.widget.TextView
    
    // Gesture control variables
    private var currentBrightness = 0.5f
    private var currentVolume = 100
    private var systemVolume = 100 // Store system volume percentage for UI/fallbacks
    private var isGesturing = false
    private var gestureType: GestureType? = null
    private var seekDelta = 0L
    private var seekStartTime = -1L
    private var pendingSubtitleTrackId: Int? = null
    private var pendingSubtitleTrackName: String? = null
    private var pendingAudioTrackId: Int? = null
    private var pendingAudioTrackName: String? = null
    private var currentZoomScale = 1f
    private val minZoomScale = 0.5f
    private val maxZoomScale = 1f
    private var currentTranslationX = 0f
    private var currentTranslationY = 0f
    private var blockSingleFingerGesturesUntilRelease = false
    private var videoMarkedAsCompleted = false
    private var pendingSavedProgress = 0L
    private var pendingVideoDuration = 0L
    
    // State for video restoration after background/foreground
    private var wasPlayingBeforeBackground = false
    private var currentVideoPath: String? = null
    private var currentVideoPosition: Long = 0L
    private var isInBackground = false
    
    private enum class GestureType { BRIGHTNESS, VOLUME, SEEK, PAN }

    // ── Permission launchers ────────────────────────────────────────────────
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            checkManageStoragePermission()
        } else {
            showPermissionDeniedUI()
        }
    }

    private val requestManageStorageLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { resultCode ->
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
            if (android.os.Environment.isExternalStorageManager()) {
                loadVideos()
            } else {
                showPermissionDeniedUI()
            }
        } else {
            loadVideos()
        }
    }

    
    // ── Lifecycle ──────────────────────────────────────────────────────────
    override fun onCreate(savedInstanceState: Bundle?) {
        AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_YES)
        try {
            super.onCreate(savedInstanceState)
            setContentView(R.layout.activity_main)

            folderRecyclerView = findViewById(R.id.folderRecyclerView)
            videoRecyclerView  = findViewById(R.id.videoRecyclerView)
            vlcVideoLayout     = findViewById(R.id.surfaceView)
            
            folderSwipeRefresh = findViewById(R.id.folderSwipeRefresh)
            videoSwipeRefresh = findViewById(R.id.videoSwipeRefresh)
            noVideosLayout     = findViewById(R.id.noVideosLayout)
            permissionDeniedLayout = findViewById(R.id.permissionDeniedLayout)
            btnGrantPermission = findViewById(R.id.btnGrantPermission)


            playerContainer    = findViewById(R.id.playerContainer)
            playbackControls   = findViewById(R.id.playbackControls)
            tvVideoTitle       = findViewById(R.id.tvVideoTitle)
            btnCloseVideo      = findViewById(R.id.btnCloseVideo)
            btnPrevious        = findViewById(R.id.btnPrevious)
            btnPlayPause       = findViewById(R.id.btnPlayPause)
            btnNext            = findViewById(R.id.btnNext)
            btnContinueFromPosition = findViewById(R.id.btnContinueFromPosition)
            tvCurrentTime      = findViewById(R.id.tvCurrentTime)
            tvTotalTime        = findViewById(R.id.tvTotalTime)
            seekBar            = findViewById(R.id.seekBar)
            btnOrientation     = findViewById(R.id.btnOrientation)
            btnAudioTracks     = findViewById(R.id.btnAudioTracks)
            btnSubtitleTracks  = findViewById(R.id.btnSubtitleTracks)
            topControlsContainer = findViewById(R.id.topControlsContainer)
            bottomControlsContainer = findViewById(R.id.bottomControlsContainer)
            
            // Initialize multi-select UI components
            multiSelectTitleBar = findViewById(R.id.multiSelectTitleBar)
            btnMultiSelectDelete = findViewById(R.id.btnMultiSelectDelete)
            btnMultiSelectClose = findViewById(R.id.btnMultiSelectClose)
            tvSelectedCount = findViewById(R.id.tvSelectedCount)

            // Measure control heights for gesture restriction
            playbackControls.viewTreeObserver.addOnGlobalLayoutListener(object : android.view.ViewTreeObserver.OnGlobalLayoutListener {
                override fun onGlobalLayout() {
                    if (topControlsContainer.height > 0) {
                        topControlsHeight = topControlsContainer.height
                    }
                    if (bottomControlsContainer.height > 0) {
                        bottomControlsHeight = bottomControlsContainer.height
                    }
                    // Once we have both (or if we just want to keep updating), we could remove listener, 
                    // but keeping it handles orientation changes.
                }
            })

            gestureOverlay     = findViewById(R.id.gestureOverlay)
            brightnessIndicator = findViewById(R.id.brightnessIndicator)
            volumeIndicator    = findViewById(R.id.volumeIndicator)
            seekIndicator      = findViewById(R.id.seekIndicator)
            zoomIndicator      = findViewById(R.id.zoomIndicator)
            tvBrightnessPercent = findViewById(R.id.tvBrightnessPercent)
            tvVolumePercent    = findViewById(R.id.tvVolumePercent)
            tvSeekTime         = findViewById(R.id.tvSeekTime)
            tvSeekOffset       = findViewById(R.id.tvSeekOffset)
            tvZoomPercent      = findViewById(R.id.tvZoomPercent)
            // ivSeekIcon initialization removed
            brightnessProgressBar = findViewById(R.id.brightnessProgressBar)
            volumeProgressBar   = findViewById(R.id.volumeProgressBar)
            
            btnLockScreen      = findViewById(R.id.btnLockScreen)
            btnLockScreen.setOnClickListener {
                unlockUi()
            }

            sharedPrefs = getSharedPreferences("OniPlayerPrefs", Context.MODE_PRIVATE)
            audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            
            // Don't clear video progress - we want to remember last watch point
            
            // Load saved system volume (used when outside videos)
            val maxVol = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
            val currentVol = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
            systemVolume = if (maxVol > 0) (currentVol * 100 / maxVol) else 70
            
            // If we have a pending restoration from a previous crash/kill, restore it now
            val pendingRestore = sharedPrefs.getInt(PREF_ORIGINAL_SYSTEM_VOLUME, -1)
            if (pendingRestore != -1) {
                audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, pendingRestore, 0)
                sharedPrefs.edit().remove(PREF_ORIGINAL_SYSTEM_VOLUME).apply()
                // Re-calculate systemVolume after restoration
                val restoredVol = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
                systemVolume = if (maxVol > 0) (restoredVol * 100 / maxVol) else 70
            }
            
            // Load default video volume (fallback for videos without saved volume)
            val savedVolume = sharedPrefs.getInt("saved_volume", -1)
            currentVolume = if (savedVolume != -1) savedVolume else systemVolume

            val savedBrightness = sharedPrefs.getFloat("saved_brightness", -1f)
            if (savedBrightness == -1f) {
                currentBrightness = try {
                    android.provider.Settings.System.getInt(contentResolver, android.provider.Settings.System.SCREEN_BRIGHTNESS) / 255f
                } catch (e: Exception) {
                    0.5f
                }
            } else {
                currentBrightness = savedBrightness
            }
            
            setupPlayerControls()

            folderRecyclerView.layoutManager = LinearLayoutManager(this)
            videoRecyclerView.layoutManager  = LinearLayoutManager(this)

            // Setup permission button click listener
            btnGrantPermission.setOnClickListener {
                handleGrantPermissionClick()
            }

            // Back-press navigation: PLAYER → VIDEOS → FOLDERS → system
            onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    // Cancel refresh if in progress
                    cancelRefresh()
                    
                    if (isMultiSelectMode) {
                        exitMultiSelectMode()
                    } else {
                        when (currentScreen) {
                            Screen.PLAYER -> {
                                if (isUiLocked) {
                                    showLockIconForOneSec()
                                } else {
                                    stopVideo()
                                    showVideoList()
                                }
                            }
                            Screen.VIDEOS -> showFolderList()
                            Screen.FOLDERS -> {
                                isEnabled = false
                                onBackPressedDispatcher.onBackPressed()
                            }
                        }
                    }
                }
            })

            setupGestureDetector()
            setupReloadFeatures()
            setupMultiSelect()
            checkPermissionAndLoadVideos()

            // Handle intent from "Open with" menu
            handleIntent(intent)

        } catch (e: Exception) {
            e.printStackTrace()
            android.util.Log.e("OniPlayer", "Crash in onCreate: ${e.message}", e)
            Toast.makeText(this, "Error: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent) {
        val action = intent.action
        val data = intent.data

        if (action == Intent.ACTION_VIEW && data != null) {
            android.util.Log.d("OniPlayer", "Received VIEW intent: $data")
            android.util.Log.d("OniPlayer", "Intent scheme: ${data.scheme}, authority: ${data.authority}")
            
            // Convert URI to file path
            val filePath = getPathFromUri(data)
            if (filePath != null) {
                android.util.Log.d("OniPlayer", "File path resolved: $filePath")
                
                // Try to play immediately, if videos are loaded it will work
                // If not loaded yet, it will still work for direct playback
                playVideoFromPath(filePath)
            } else {
                android.util.Log.e("OniPlayer", "Failed to resolve file path from URI: $data")
                Toast.makeText(this, "Unable to open video file", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun getPathFromUri(uri: Uri): String? {
        return when (uri.scheme) {
            "file" -> uri.path
            "content" -> {
                // Try multiple methods to get the file path from content URI
                getPathFromContentUri(uri)
            }
            else -> null
        }
    }

    private fun getPathFromContentUri(uri: Uri): String? {
        // Method 1: Try MediaStore DATA column (works for most content URIs)
        val projection = arrayOf(android.provider.MediaStore.Video.Media.DATA)
        val cursor = contentResolver.query(uri, projection, null, null, null)
        cursor?.use {
            val columnIndex = it.getColumnIndexOrThrow(android.provider.MediaStore.Video.Media.DATA)
            if (it.moveToFirst()) {
                val path = it.getString(columnIndex)
                if (path != null && File(path).exists()) {
                    android.util.Log.d("OniPlayer", "Got path from MediaStore DATA: $path")
                    return path
                }
            }
        }

        // Method 2: Try using _ID to find the file path (works for download manager URIs)
        val id = uri.lastPathSegment?.toLongOrNull()
        if (id != null) {
            try {
                val selection = "${android.provider.MediaStore.Video.Media._ID} = ?"
                val selectionArgs = arrayOf(id.toString())
                val cursor2 = contentResolver.query(
                    android.provider.MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                    arrayOf(android.provider.MediaStore.Video.Media.DATA),
                    selection,
                    selectionArgs,
                    null
                )
                cursor2?.use {
                    val columnIndex = it.getColumnIndexOrThrow(android.provider.MediaStore.Video.Media.DATA)
                    if (it.moveToFirst()) {
                        val path = it.getString(columnIndex)
                        if (path != null && File(path).exists()) {
                            android.util.Log.d("OniPlayer", "Got path from _ID query: $path")
                            return path
                        }
                    }
                }
            } catch (e: Exception) {
                android.util.Log.w("OniPlayer", "Failed to query by _ID: ${e.message}")
            }
        }

        // Method 3: Try using openFileDescriptor to get the actual file path
        try {
            contentResolver.openFileDescriptor(uri, "r")?.use { pfd ->
                val path = getFileDescriptorPath(pfd)
                if (path != null && File(path).exists()) {
                    android.util.Log.d("OniPlayer", "Got path from FileDescriptor: $path")
                    return path
                }
            }
        } catch (e: Exception) {
            android.util.Log.w("OniPlayer", "Failed to get path from FileDescriptor: ${e.message}")
        }

        // Method 4: Try DocumentsContract API for storage access framework URIs
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.KITKAT) {
            try {
                val path = getPathFromDocumentsUri(uri)
                if (path != null && File(path).exists()) {
                    android.util.Log.d("OniPlayer", "Got path from DocumentsContract: $path")
                    return path
                }
            } catch (e: Exception) {
                android.util.Log.w("OniPlayer", "Failed to get path from DocumentsContract: ${e.message}")
            }
        }

        android.util.Log.e("OniPlayer", "Could not resolve file path for URI: $uri")
        return null
    }

    private fun getFileDescriptorPath(pfd: android.os.ParcelFileDescriptor): String? {
        // Try to get the path from the file descriptor using reflection
        return try {
            val field = android.os.ParcelFileDescriptor::class.java.getDeclaredField("mFd")
            field.isAccessible = true
            val fd = field.getInt(pfd) as Int
            val procFile = File("/proc/self/fd/$fd")
            if (procFile.exists()) {
                procFile.canonicalPath
            } else null
        } catch (e: Exception) {
            android.util.Log.w("OniPlayer", "Failed to get path from fd: ${e.message}")
            null
        }
    }

    private fun getPathFromDocumentsUri(uri: Uri): String? {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.KITKAT) {
            return try {
                val docId = DocumentsContract.getDocumentId(uri)
                
                // Handle different URI patterns
                when {
                    // External storage URIs
                    uri.authority == "com.android.externalstorage.documents" -> {
                        val parts = docId.split(":")
                        if (parts.size >= 2) {
                            val type = parts[0]
                            val path = parts[1]
                            if (type == "primary") {
                                "${Environment.getExternalStorageDirectory()}/$path"
                            } else {
                                // Handle secondary storage (SD cards)
                                "/storage/$type/$path"
                            }
                        } else null
                    }
                    // Downloads provider URIs
                    uri.authority == "com.android.providers.downloads.documents" -> {
                        val id = docId.toLongOrNull()
                        if (id != null) {
                            val contentUri = android.net.Uri.parse("content://downloads/public_downloads")
                            val projection = arrayOf(android.provider.MediaStore.Downloads.DATA)
                            val cursor = contentResolver.query(
                                android.net.Uri.withAppendedPath(contentUri, "/$id"),
                                projection,
                                null,
                                null,
                                null
                            )
                            cursor?.use {
                                val columnIndex = it.getColumnIndexOrThrow(android.provider.MediaStore.Downloads.DATA)
                                if (it.moveToFirst()) {
                                    it.getString(columnIndex)
                                } else null
                            }
                        } else null
                    }
                    // Media provider URIs
                    uri.authority == "com.android.providers.media.documents" -> {
                        val parts = docId.split(":")
                        if (parts.size >= 2) {
                            val type = parts[0]
                            val id = parts[1]
                            if (type == "video") {
                                val contentUri = android.provider.MediaStore.Video.Media.EXTERNAL_CONTENT_URI
                                val projection = arrayOf(android.provider.MediaStore.Video.Media.DATA)
                                val selection = "${android.provider.MediaStore.Video.Media._ID} = ?"
                                val cursor = contentResolver.query(
                                    contentUri,
                                    projection,
                                    selection,
                                    arrayOf(id),
                                    null
                                )
                                cursor?.use {
                                    val columnIndex = it.getColumnIndexOrThrow(android.provider.MediaStore.Video.Media.DATA)
                                    if (it.moveToFirst()) {
                                        it.getString(columnIndex)
                                    } else null
                                }
                            } else null
                        } else null
                    }
                    else -> null
                }
            } catch (e: Exception) {
                android.util.Log.w("OniPlayer", "Failed to get path from DocumentsContract: ${e.message}")
                null
            }
        }
        return null
    }

    private fun playVideoFromPath(filePath: String) {
        val video = allVideos.find { it.path == filePath }
        if (video != null) {
            android.util.Log.d("OniPlayer", "Found video: ${video.title}")
            
            // Find the folder containing this video
            val videoFile = File(video.path)
            val parentPath = videoFile.parent ?: return
            val folder = folders.find { it.path == parentPath }
            
            if (folder != null) {
                currentPlayingIndex = folder.videos.indexOfFirst { it.path == video.path }
                
                showVideoListForFolder(folder)
                
                handler.postDelayed({
                    if (currentPlayingIndex >= 0 && currentPlayingIndex < currentPlaylist.size) {
                        playVideo(currentPlaylist[currentPlayingIndex])
                    }
                }, 500)
            } else {
                Toast.makeText(this, "Video not found in library", Toast.LENGTH_LONG).show()
            }
        } else {
            // Video not found in library - try to play it directly
            android.util.Log.d("OniPlayer", "Video not in library, attempting direct playback: $filePath")
            val videoFile = File(filePath)
            if (videoFile.exists()) {
                // Create a temporary VideoItem for direct playback
                val tempVideo = VideoItem(
                    id = -1,
                    title = videoFile.nameWithoutExtension,
                    path = filePath,
                    duration = 0L,
                    size = videoFile.length()
                )
                
                // Play directly without adding to library
                playVideo(tempVideo)
            } else {
                Toast.makeText(this, "Video file not found: $filePath", Toast.LENGTH_LONG).show()
                android.util.Log.e("OniPlayer", "Video file does not exist: $filePath")
            }
        }
    }

    // ── Permission ─────────────────────────────────────────────────────────
    private fun checkPermissionAndLoadVideos() {
        val permission = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU)
            Manifest.permission.READ_MEDIA_VIDEO
        else
            Manifest.permission.READ_EXTERNAL_STORAGE

        if (ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED) {
            checkManageStoragePermission()
        } else {
            // Check if we should show permission rationale (user denied before)
            if (shouldShowRequestPermissionRationale(permission)) {
                showPermissionDeniedUI()
            } else {
                requestPermissionLauncher.launch(permission)
            }
        }
    }

    private fun checkManageStoragePermission() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
            if (android.os.Environment.isExternalStorageManager()) {
                loadVideos()
            } else {
                requestManageStoragePermission()
            }
        } else {
            loadVideos()
        }
    }

    private fun requestManageStoragePermission() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
            try {
                val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                intent.addCategory("android.intent.category.DEFAULT")
                intent.data = Uri.parse(String.format("package:%s", packageName))
                requestManageStorageLauncher.launch(intent)
            } catch (e: Exception) {
                val intent = Intent()
                intent.action = Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION
                requestManageStorageLauncher.launch(intent)
            }
        }
    }

    private fun showPermissionDeniedUI() {
        folderSwipeRefresh.visibility = android.view.View.GONE
        videoSwipeRefresh.visibility = android.view.View.GONE
        folderRecyclerView.visibility = android.view.View.GONE
        videoRecyclerView.visibility = android.view.View.GONE
        noVideosLayout.visibility = android.view.View.GONE
        playerContainer.visibility = android.view.View.GONE
        permissionDeniedLayout.visibility = android.view.View.VISIBLE
    }

    private fun handleGrantPermissionClick() {
        val permission = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU)
            Manifest.permission.READ_MEDIA_VIDEO
        else
            Manifest.permission.READ_EXTERNAL_STORAGE

        val hasVideoPermission = ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED
        val hasManageStoragePermission = android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.R || 
                                       android.os.Environment.isExternalStorageManager()

        when {
            !hasVideoPermission -> {
                // Request video permission first
                if (shouldShowRequestPermissionRationale(permission)) {
                    openAppSettings()
                } else {
                    requestPermissionLauncher.launch(permission)
                }
            }
            !hasManageStoragePermission -> {
                // Request manage storage permission
                requestManageStoragePermission()
            }
            else -> {
                // All permissions granted, hide permission UI
                permissionDeniedLayout.visibility = android.view.View.GONE
                loadVideos()
            }
        }
    }

    private fun openAppSettings() {
        val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
            data = Uri.fromParts("package", packageName, null)
        }
        startActivity(intent)
    }

    
    // ── Data loading ───────────────────────────────────────────────────────
    private fun loadVideos() {
        loadVideosWithoutShowingList()
        showFolderList()
    }
    
    private fun loadVideosWithoutShowingList() {
        try {
            allVideos.clear()

            val projection = arrayOf(
                MediaStore.Video.Media._ID,
                MediaStore.Video.Media.TITLE,
                MediaStore.Video.Media.DISPLAY_NAME,
                MediaStore.Video.Media.DATA,
                MediaStore.Video.Media.DURATION,
                MediaStore.Video.Media.SIZE
            )

            // Query ALL external volumes (primary storage + SD cards)
            val urisToQuery = mutableListOf<android.net.Uri>()
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                try {
                    MediaStore.getExternalVolumeNames(this).forEach { volumeName ->
                        urisToQuery.add(MediaStore.Video.Media.getContentUri(volumeName))
                    }
                } catch (e: Exception) {
                    urisToQuery.add(MediaStore.Video.Media.EXTERNAL_CONTENT_URI)
                }
            } else {
                urisToQuery.add(MediaStore.Video.Media.EXTERNAL_CONTENT_URI)
            }

            for (uri in urisToQuery) {
                val cursor: Cursor? = try {
                    contentResolver.query(
                        uri,
                        projection, null, null,
                        MediaStore.Video.Media.TITLE + " ASC"
                    )
                } catch (e: Exception) {
                    android.util.Log.w("OniPlayer", "Failed to query volume $uri: ${e.message}")
                    continue
                }

                cursor?.use {
                    val idCol       = it.getColumnIndexOrThrow(MediaStore.Video.Media._ID)
                    val titleCol    = it.getColumnIndexOrThrow(MediaStore.Video.Media.TITLE)
                    val displayCol  = it.getColumnIndex(MediaStore.Video.Media.DISPLAY_NAME)
                    val dataCol     = it.getColumnIndexOrThrow(MediaStore.Video.Media.DATA)
                    val durationCol = it.getColumnIndexOrThrow(MediaStore.Video.Media.DURATION)
                    val sizeCol     = it.getColumnIndexOrThrow(MediaStore.Video.Media.SIZE)

                    while (it.moveToNext()) {
                        val path  = it.getString(dataCol) ?: continue
                        if (path.isBlank()) continue
                        val fetchedTitle = it.getString(titleCol)
                        val displayName = if (displayCol != -1) it.getString(displayCol) else null
                        
                        var title = when {
                            !displayName.isNullOrBlank() -> displayName.substringBeforeLast(".")
                            !fetchedTitle.isNullOrBlank() -> fetchedTitle
                            else -> File(path).nameWithoutExtension
                        }
                        if (title.isBlank()) title = File(path).name
                        allVideos.add(
                            VideoItem(
                                id       = it.getLong(idCol),
                                title    = title,
                                path     = path,
                                duration = it.getLong(durationCol),
                                size     = it.getLong(sizeCol)
                            )
                        )
                    }
                }
            }

            // Remove duplicates (same path may appear across multiple volume queries)
            val seen = mutableSetOf<String>()
            val initialResults = allVideos.filter { seen.add(it.path) }
            allVideos.clear()
            allVideos.addAll(initialResults)

            // Manual scan fallback to find newly added videos missed by MediaStore
            try {
                val externalStorage = Environment.getExternalStorageDirectory()
                if (externalStorage.exists() && externalStorage.isDirectory) {
                    val retriever = MediaMetadataRetriever()
                    performManualScan(externalStorage, allVideos, retriever)
                    try { retriever.release() } catch (e: Exception) {}
                }
            } catch (e: Exception) {
                android.util.Log.e("OniPlayer", "Manual scan error: ${e.message}")
            }

            // Debug logging
            android.util.Log.d("OniPlayer", "Total videos found: ${allVideos.size}")
            
            // Group videos by their immediate parent folder - this ensures every folder with videos is included
            val folderMap = mutableMapOf<String, MutableList<VideoItem>>()
            
            allVideos.forEach { video ->
                val videoFile = File(video.path)
                val parentPath = videoFile.parent ?: "Unknown"
                
                android.util.Log.d("OniPlayer", "Video: ${video.title} -> Parent: $parentPath")
                
                if (folderMap[parentPath] == null) {
                    folderMap[parentPath] = mutableListOf()
                }
                folderMap[parentPath]?.add(video)
            }
            
            android.util.Log.d("OniPlayer", "Unique folders found: ${folderMap.keys.size}")
            folderMap.keys.forEach { folderPath ->
                android.util.Log.d("OniPlayer", "Folder: $folderPath has ${folderMap[folderPath]?.size} videos")
            }
            
            // Convert to FolderItem list - only include folders that actually contain videos
            folders = folderMap.map { (folderPath, videos) ->
                if (videos.isNotEmpty()) {
                    val folderFile = File(folderPath)
                    val externalStoragePath = Environment.getExternalStorageDirectory().absolutePath
                    val displayName = when {
                        folderPath == externalStoragePath -> "Internal Storage"
                        folderFile.name.isNullOrBlank() -> {
                            val name = folderPath.substringAfterLast("/")
                            if (name.isBlank()) "Unknown" else name
                        }
                        else -> folderFile.name
                    }
                    
                    android.util.Log.d("OniPlayer", "Creating folder: $displayName ($folderPath) with ${videos.size} videos")
                    
                    FolderItem(
                        name   = displayName,
                        path   = folderPath,
                        videos = videos.sortedWith(Comparator { a, b -> naturalSortComparator.compare(a.title, b.title) })
                    )
                } else null
            }
            .filterNotNull()
            .sortedWith(Comparator { a, b ->
                // Put Internal Storage first, then natural sort
                when {
                    a.name == "Internal Storage" -> -1
                    b.name == "Internal Storage" -> 1
                    else -> naturalSortComparator.compare(a.name, b.name)
                }
            })
            
            android.util.Log.d("OniPlayer", "Final folder list size: ${folders.size}")
            folders.forEach { folder ->
                android.util.Log.d("OniPlayer", "Final folder: ${folder.name} (${folder.path}) with ${folder.videos.size} videos")
            }

        } catch (e: Exception) {
            e.printStackTrace()
            android.util.Log.e("OniPlayer", "Error loading videos: ${e.message}", e)
            Toast.makeText(this, "Error loading videos: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun performManualScan(directory: File, results: MutableList<VideoItem>, retriever: MediaMetadataRetriever) {
        val files = directory.listFiles() ?: return
        
        for (file in files) {
            try {
                if (file.isDirectory) {
                    // Skip hidden directories and Android system folder to keep it fast
                    if (file.name.startsWith(".") || file.name.equals("Android", ignoreCase = true)) continue
                    performManualScan(file, results, retriever)
                } else {
                    val extension = file.extension.lowercase(Locale.ROOT)
                    if (extension in VIDEO_EXTENSIONS) {
                        // Check if already in results to avoid duplicates
                        if (results.none { it.path == file.absolutePath }) {
                            var duration = 0L
                            try {
                                retriever.setDataSource(file.absolutePath)
                                val durationStr = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                                duration = durationStr?.toLong() ?: 0L
                            } catch (e: Exception) {
                                android.util.Log.w("OniPlayer", "Could not get duration for ${file.name}")
                            }
                            
                            results.add(
                                VideoItem(
                                    id = -1, // Dummy ID for non-MediaStore files
                                    title = file.nameWithoutExtension,
                                    path = file.absolutePath,
                                    duration = duration,
                                    size = file.length()
                                )
                            )
                        }
                    }
                }
            } catch (e: Exception) {
                // Skip folders we can't access
                continue
            }
        }
    }

    // Reload functionality
    private fun setupReloadFeatures() {
        // Setup SwipeRefreshLayout for folders
        folderSwipeRefresh.setOnRefreshListener {
            refreshVideoLibrary()
        }

        // Setup SwipeRefreshLayout for videos (inside folders)
        videoSwipeRefresh.setOnRefreshListener {
            refreshVideoLibrary()
        }

        
        // Set colors for swipe refresh - completely dark themed arrows
        val refreshColors = intArrayOf(
            ContextCompat.getColor(this, R.color.text_secondary), // Subtle gray
            ContextCompat.getColor(this, R.color.dark_surface_alt), // Darker surface
            ContextCompat.getColor(this, R.color.text_secondary), // Subtle gray
            ContextCompat.getColor(this, R.color.dark_surface_alt)  // Darker surface
        )
        
        folderSwipeRefresh.setColorSchemeColors(*refreshColors)
        videoSwipeRefresh.setColorSchemeColors(*refreshColors)

        
        // Set progress view offset to avoid title bar overlap
        val actionBarHeight = getActionBarHeight()
        folderSwipeRefresh.setProgressViewOffset(false, actionBarHeight, actionBarHeight + 100)
        videoSwipeRefresh.setProgressViewOffset(false, actionBarHeight, actionBarHeight + 100)

        
        // Set custom dark themed background for refresh animation
        val refreshBgColor = ContextCompat.getColor(this, R.color.dark_surface)
        folderSwipeRefresh.setProgressBackgroundColorSchemeColor(refreshBgColor)
        videoSwipeRefresh.setProgressBackgroundColorSchemeColor(refreshBgColor)

    }
    
    private fun getActionBarHeight(): Int {
        val tv = TypedValue()
        return if (theme.resolveAttribute(android.R.attr.actionBarSize, tv, true)) {
            TypedValue.complexToDimensionPixelSize(tv.data, resources.displayMetrics)
        } else {
            // Default action bar height: 56dp converted to pixels
            (56 * resources.displayMetrics.density).toInt()
        }
    }
    
    private fun refreshVideoLibrary() {
        // Cancel any existing refresh
        cancelRefresh()
        
        isRefreshing = true
        
        // Store current state to restore after refresh
        val wasInFolder = currentScreen == Screen.VIDEOS
        val savedFolderPath = currentFolderPath
        
        // Show refresh indicator on active swipe refresh
        if (currentScreen == Screen.FOLDERS) {
            folderSwipeRefresh.isRefreshing = true
        } else if (currentScreen == Screen.VIDEOS) {
            videoSwipeRefresh.isRefreshing = true
        }
        
        // Trigger a system media scan to encourage MediaStore to update
        try {
            val rootPath = Environment.getExternalStorageDirectory().absolutePath
            MediaScannerConnection.scanFile(this, arrayOf(rootPath), null) { path, uri ->
                android.util.Log.d("OniPlayer", "System scan triggered for $path -> $uri")
            }
        } catch (e: Exception) {
            android.util.Log.e("OniPlayer", "Failed to trigger system scan: ${e.message}")
        }
        
        // Reload videos without showing folder list
        loadVideosWithoutShowingList()
        
        // Create and store the callback runnable so it can be cancelled
        refreshCallbackRunnable = Runnable {
            // Only proceed if still refreshing (not cancelled by user navigation)
            if (!isRefreshing) {
                android.util.Log.d("OniPlayer", "Refresh was cancelled, skipping state restoration")
                return@Runnable
            }
            
            // Hide refresh indicators
            folderSwipeRefresh.isRefreshing = false
            videoSwipeRefresh.isRefreshing = false
            isRefreshing = false
            refreshCallbackRunnable = null
            
            if (currentScreen == Screen.PLAYER) {
                // If the user has started playing a video, update the background list/adapters 
                // so they are ready when the user exits the player, but do NOT change view visibilities.
                val targetFolder = folders.find { it.path == savedFolderPath }
                if (targetFolder != null) {
                    currentPlaylist = targetFolder.videos
                    videoRecyclerView.adapter = VideoAdapter(
                        videos = targetFolder.videos,
                        sharedPrefs = sharedPrefs,
                        onVideoClick = { video ->
                            if (!isMultiSelectMode) {
                                val layoutManager = videoRecyclerView.layoutManager as LinearLayoutManager
                                savedVideoListScrollPosition = layoutManager.findFirstVisibleItemPosition()
                                currentPlayingIndex = targetFolder.videos.indexOf(video)
                                playVideo(video)
                            }
                        },
                        onVideoLongClick = { video ->
                            enterMultiSelectMode()
                            toggleVideoSelection(video.path ?: "")
                            updateVideoAdapter()
                        },
                        isMultiSelectMode = isMultiSelectMode,
                        selectedVideos = selectedVideos,
                        onSelectionToggle = { videoPath ->
                            toggleVideoSelection(videoPath)
                            updateVideoAdapter()
                        }
                    )
                }
            } else {
                // If we were in a folder before refresh, try to restore that state
                if (wasInFolder && savedFolderPath.isNotEmpty()) {
                    // Find the folder by path (unique identifier, unlike name)
                    val targetFolder = folders.find { it.path == savedFolderPath }
                    if (targetFolder != null) {
                        showVideoListForFolder(targetFolder)
                    } else {
                        // Folder no longer exists, show folder list
                        showFolderList()
                    }
                } else {
                    // If we were in folder list, show it
                    showFolderList()
                }
            }
        }
        
        // Post the delayed callback
        handler.postDelayed(refreshCallbackRunnable!!, 1000)
    }
    
    private fun cancelRefresh() {
        if (isRefreshing) {
            android.util.Log.d("OniPlayer", "Cancelling refresh due to user navigation")
            isRefreshing = false
            
            // Remove the pending callback if it exists
            refreshCallbackRunnable?.let {
                handler.removeCallbacks(it)
                refreshCallbackRunnable = null
            }
            
            // Hide refresh indicators
            folderSwipeRefresh.isRefreshing = false
            videoSwipeRefresh.isRefreshing = false
        }
    }

    // ── Multi-select Setup ─────────────────────────────────────────────────
    private fun setupMultiSelect() {
        btnMultiSelectClose.setOnClickListener {
            exitMultiSelectMode()
        }
        
        btnMultiSelectDelete.setOnClickListener {
            showDeleteConfirmationDialog()
        }
    }
    
    private fun enterMultiSelectMode() {
        isMultiSelectMode = true
        selectedFolders.clear()
        selectedVideos.clear()
        multiSelectTitleBar.visibility = android.view.View.VISIBLE
        updateSelectedCount()
        
        // Hide arrow button when in multi-select mode
        supportActionBar?.setDisplayHomeAsUpEnabled(false)
        supportActionBar?.setHomeButtonEnabled(false)
        
        // Disable swipe refresh when in multi-select mode
        folderSwipeRefresh.isEnabled = false
        videoSwipeRefresh.isEnabled = false
        
        // Add bottom padding to prevent overlap with multi-select bar
        val bottomPadding = 64.dpToPx()
        folderRecyclerView.setPadding(0, folderRecyclerView.paddingTop, 0, bottomPadding)
        videoRecyclerView.setPadding(0, videoRecyclerView.paddingTop, 0, bottomPadding)
    }
    
    private fun exitMultiSelectMode() {
        isMultiSelectMode = false
        selectedFolders.clear()
        selectedVideos.clear()
        multiSelectTitleBar.visibility = android.view.View.GONE
        
        // Restore arrow button if we're in VIDEOS screen (inside a folder)
        if (currentScreen == Screen.VIDEOS) {
            supportActionBar?.setDisplayHomeAsUpEnabled(true)
            supportActionBar?.setHomeButtonEnabled(true)
        }
        
        // Re-enable swipe refresh
        folderSwipeRefresh.isEnabled = true
        videoSwipeRefresh.isEnabled = true
        
        // Restore original padding
        folderRecyclerView.setPadding(0, folderRecyclerView.paddingTop, 0, 0)
        videoRecyclerView.setPadding(0, videoRecyclerView.paddingTop, 0, 0)
        
        // Refresh the current view to clear selection UI
        when (currentScreen) {
            Screen.FOLDERS -> showFolderList()
            Screen.VIDEOS -> {
                // Use path (unique) instead of name to find the folder
                val folder = folders.find { it.path == currentFolderPath } ?: return
                showVideoListForFolder(folder)
            }
            else -> {}
        }
    }
    
    private fun Int.dpToPx(): Int {
        return (this * resources.displayMetrics.density).toInt()
    }
    
    private fun updateSelectedCount() {
        val totalCount = selectedFolders.size + selectedVideos.size
        tvSelectedCount.text = if (totalCount == 1) "1 selected" else "$totalCount selected"
    }
    
    private fun toggleFolderSelection(folderPath: String) {
        if (selectedFolders.contains(folderPath)) {
            selectedFolders.remove(folderPath)
        } else {
            selectedFolders.add(folderPath)
        }
        updateSelectedCount()
    }
    
    private fun toggleVideoSelection(videoPath: String) {
        if (selectedVideos.contains(videoPath)) {
            selectedVideos.remove(videoPath)
        } else {
            selectedVideos.add(videoPath)
        }
        updateSelectedCount()
    }
    
    private fun showDeleteConfirmationDialog() {
        val totalCount = selectedFolders.size + selectedVideos.size
        val titleText = if (totalCount == 1) "Delete item?" else "Delete $totalCount items?"
        val messageText = if (totalCount == 1) {
            "Are you sure you want to permanently delete this item? This action cannot be undone."
        } else {
            "Are you sure you want to permanently delete these $totalCount items? This action cannot be undone."
        }

        val dialogView = layoutInflater.inflate(R.layout.dialog_delete_confirm, null)
        val tvTitle = dialogView.findViewById<android.widget.TextView>(R.id.dialogTitle)
        val tvMessage = dialogView.findViewById<android.widget.TextView>(R.id.dialogMessage)
        val btnCancel = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.btnCancel)
        val btnDelete = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.btnDelete)

        tvTitle.text = titleText
        tvMessage.text = messageText

        val dialog = com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
            .setView(dialogView)
            .create()

        // Make background transparent so rounded corner card is fully visible without default alert background showing behind it
        dialog.window?.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT))

        btnCancel.setOnClickListener {
            dialog.dismiss()
        }

        btnDelete.setOnClickListener {
            deleteSelectedItems()
            dialog.dismiss()
        }

        dialog.show()
    }

        
    private fun deleteSelectedItems() {
        var deletedCount = 0
        
        // Delete selected folders
        selectedFolders.forEach { folderPath ->
            try {
                val folder = File(folderPath)
                if (folder.exists() && folder.isDirectory) {
                    if (deleteFolderVideosOnly(folder)) {
                        deletedCount++
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("OniPlayer", "Error deleting folder: $folderPath", e)
            }
        }
        
        // Delete selected videos
        selectedVideos.forEach { videoPath ->
            try {
                val video = File(videoPath)
                if (video.exists() && video.isFile) {
                    if (video.delete()) {
                        deletedCount++
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("OniPlayer", "Error deleting video: $videoPath", e)
            }
        }
        
        Toast.makeText(this, "Deleted $deletedCount items", Toast.LENGTH_SHORT).show()
        exitMultiSelectMode()
        refreshVideoLibrary()
    }
    
    private fun deleteFolderVideosOnly(folder: File): Boolean {
        return try {
            if (!folder.exists() || !folder.isDirectory) return false
            
            var deletedAny = false
            val contents = folder.listFiles() ?: return false
            
            for (child in contents) {
                // Delete only video files directly inside this folder.
                // Do NOT touch nested folders (subdirectories) or non-video files.
                if (child.isFile) {
                    val extension = child.extension.lowercase(Locale.ROOT)
                    if (extension in VIDEO_EXTENSIONS) {
                        if (child.delete()) {
                            deletedAny = true
                        }
                    }
                }
            }
            
            // Delete the parent folder directory ONLY if it is now completely empty
            // (i.e., no nested subfolders or non-video files remain inside it)
            val remainingContents = folder.listFiles()
            if (remainingContents != null && remainingContents.isEmpty()) {
                if (folder.delete()) {
                    deletedAny = true
                }
            }
            
            deletedAny
        } catch (e: Exception) {
            android.util.Log.e("OniPlayer", "Error deleting folder videos: ${folder.absolutePath}", e)
            false
        }
    }
    
    private fun updateFolderAdapter() {
        (folderRecyclerView.adapter as? FolderAdapter)?.let { adapter ->
            // Update the existing adapter without recreating it to prevent scroll jumping
            adapter.updateSelectionState(selectedFolders, isMultiSelectMode)
        }
    }
    
    private fun updateVideoAdapter() {
        (videoRecyclerView.adapter as? VideoAdapter)?.let { adapter ->
            // Update the existing adapter without recreating it to prevent scroll jumping
            adapter.updateSelectionState(selectedVideos, isMultiSelectMode)
        }
    }


    // ── Screen transitions ─────────────────────────────────────────────────
    private fun setupPlayerControls() {
        seekBar.max = 1000
        playerContainer.setOnClickListener { toggleControls() }
        playbackControls.setOnClickListener { toggleControls() }
        
        // Setup gesture detection
        val gestureListener = android.view.View.OnTouchListener { _, event ->
            handleGesture(event)
        }
        playerContainer.setOnTouchListener(gestureListener)
        playbackControls.setOnTouchListener(gestureListener)
        
        btnPlayPause.setOnClickListener {
            mediaPlayer?.let { player ->
                if (player.isPlaying) {
                    player.pause()
                } else {
                    player.play()
                }
                resetControlsHideTimer()
            }
        }

        btnCloseVideo.setOnClickListener {
            stopVideo()
            showVideoList()
        }
        
        btnPrevious.setOnClickListener {
            playPreviousVideo()
            resetControlsHideTimer()
        }
        
        btnNext.setOnClickListener {
            playNextVideo()
            resetControlsHideTimer()
        }
        
        btnContinueFromPosition.setOnClickListener {
            if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
                val currentVideo = currentPlaylist[currentPlayingIndex]
                val savedProgress = getVideoProgress(currentVideo.path)
                if (savedProgress > 0) {
                    mediaPlayer?.let { player ->
                        player.time = savedProgress
                        android.util.Log.d("OniPlayer", "Continued from saved position: ${formatTime(savedProgress)}")
                    }
                }
            }
            resetControlsHideTimer()
        }
        
        seekBar.setOnSeekBarChangeListener(object : android.widget.SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: android.widget.SeekBar?, progress: Int, fromUser: Boolean) {
                if (fromUser) {
                    mediaPlayer?.let { player ->
                        val newTime = (player.length * progress) / 1000
                        tvCurrentTime.text = formatTime(newTime)
                    }
                }
            }
            override fun onStartTrackingTouch(seekBar: android.widget.SeekBar?) {
                handler.removeCallbacks(hideControlsRunnable)
            }
            override fun onStopTrackingTouch(seekBar: android.widget.SeekBar?) {
                if (seekBar != null) {
                    mediaPlayer?.let { player ->
                        player.position = seekBar.progress / 1000f
                    }
                }
                resetControlsHideTimer()
            }
        })

        btnOrientation.setOnClickListener {
            val currentOrientation = sharedPrefs.getInt("video_orientation", ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE)
            val newOrientation = if (currentOrientation == ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE) {
                ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            } else {
                ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            }
            sharedPrefs.edit().putInt("video_orientation", newOrientation).apply()
            requestedOrientation = newOrientation
            resetControlsHideTimer()
        }

        btnAudioTracks.setOnClickListener {
            mediaPlayer?.let { player ->
                val wasPlaying = player.isPlaying
                if (wasPlaying) player.pause()
                showTrackSelectionBottomSheet(
                    title = "Audio tracks",
                    tracks = player.audioTracks,
                    currentTrackId = player.audioTrack,
                    player = player,
                    wasPlayingBeforeOpen = wasPlaying
                ) { id ->
                    player.audioTrack = id
                    val currentVideo = if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) currentPlaylist[currentPlayingIndex] else null
                    currentVideo?.let { video ->
                        val selectedTrackName = player.audioTracks?.firstOrNull { it.id == id }?.name
                        saveVideoAudioTrack(video.path, id, selectedTrackName)
                    }
                }
            }
        }

        btnSubtitleTracks.setOnClickListener {
            mediaPlayer?.let { player ->
                val wasPlaying = player.isPlaying
                if (wasPlaying) player.pause()
                showTrackSelectionBottomSheet(
                    title = "Subtitle tracks",
                    tracks = player.spuTracks,
                    currentTrackId = player.spuTrack,
                    player = player,
                    wasPlayingBeforeOpen = wasPlaying
                ) { id ->
                    val selectedTrackName = player.spuTracks?.firstOrNull { it.id == id }?.name
                    selectSubtitleTrackVlcStyle(id, selectedTrackName)
                    val currentVideo = if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) currentPlaylist[currentPlayingIndex] else null
                    currentVideo?.let { video ->
                        saveVideoSubtitleTrack(video.path, id, selectedTrackName)
                    }
                }
            }
        }
    }

    private fun toggleControls() {
        if (isControlsVisible) {
            handler.removeCallbacks(hideControlsRunnable)
            playbackControls.visibility = android.view.View.GONE
            isControlsVisible = false
        } else {
            playbackControls.visibility = android.view.View.VISIBLE
            topControlsContainer.visibility = android.view.View.VISIBLE
            isControlsVisible = true
            resetControlsHideTimer()
        }
    }

    private fun resetControlsHideTimer() {
        handler.removeCallbacks(hideControlsRunnable)
        mediaPlayer?.let { player ->
            if (isControlsVisible && player.isPlaying) {
                handler.postDelayed(hideControlsRunnable, 3000)
            }
        }
    }

    private fun formatTime(timeMs: Long): String {
        val totalSeconds = timeMs / 1000
        val seconds = totalSeconds % 60
        val minutes = (totalSeconds / 60) % 60
        val hours = totalSeconds / 3600
        return if (hours > 0) String.format("%d:%02d:%02d", hours, minutes, seconds)
        else String.format("%02d:%02d", minutes, seconds)
    }

    private fun lockUi() {
        if (currentScreen != Screen.PLAYER) return
        isUiLocked = true
        
        // Haptic feedback
        playerContainer.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS)
        
        // Hide playback controls and remove hide runnable
        handler.removeCallbacks(hideControlsRunnable)
        playbackControls.visibility = android.view.View.GONE
        isControlsVisible = false
        
        // Hide any active gesture overlays
        gestureOverlay.visibility = android.view.View.GONE
        brightnessIndicator.visibility = android.view.View.INVISIBLE
        volumeIndicator.visibility = android.view.View.INVISIBLE
        seekIndicator.visibility = android.view.View.INVISIBLE
        zoomIndicator.visibility = android.view.View.INVISIBLE
        
        // Show lock icon
        showLockIconForOneSec()
    }

    private fun unlockUi() {
        if (currentScreen != Screen.PLAYER) return
        isUiLocked = false
        
        // Haptic feedback
        playerContainer.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS)
        
        // Hide lock icon
        handler.removeCallbacks(hideLockIconRunnable)
        if (::btnLockScreen.isInitialized) {
            btnLockScreen.visibility = android.view.View.GONE
        }
        
        // Show controls
        playbackControls.visibility = android.view.View.VISIBLE
        topControlsContainer.visibility = android.view.View.VISIBLE
        bottomControlsContainer.visibility = android.view.View.VISIBLE
        isControlsVisible = true
        resetControlsHideTimer()
    }

    private fun showLockIconForOneSec() {
        if (currentScreen != Screen.PLAYER) return
        handler.removeCallbacks(hideLockIconRunnable)
        if (::btnLockScreen.isInitialized) {
            btnLockScreen.animate().cancel()
            btnLockScreen.visibility = android.view.View.VISIBLE
            btnLockScreen.alpha = 1f
        }
        handler.postDelayed(hideLockIconRunnable, 1000)
    }

    private fun fadeOutLockIcon() {
        if (::btnLockScreen.isInitialized) {
            btnLockScreen.animate()
                .alpha(0f)
                .setDuration(200)
                .withEndAction {
                    btnLockScreen.visibility = android.view.View.GONE
                }
                .start()
        }
    }
    
    private fun setupGestureDetector() {
        gestureDetector = android.view.GestureDetector(this, object : android.view.GestureDetector.SimpleOnGestureListener() {
            override fun onSingleTapConfirmed(e: android.view.MotionEvent): Boolean {
                toggleControls()
                return true
            }

            override fun onDoubleTap(e: android.view.MotionEvent): Boolean {
                mediaPlayer?.let { player ->
                    if (player.isPlaying) {
                        player.pause()
                    } else {
                        player.play()
                    }
                    resetControlsHideTimer()
                    return true
                }
                return false
            }

            override fun onScroll(e1: android.view.MotionEvent?, e2: android.view.MotionEvent, distanceX: Float, distanceY: Float): Boolean {
                if (e1 == null || currentScreen != Screen.PLAYER) return false
                if (e1.pointerCount > 1 || e2.pointerCount > 1) return false
                
                // Restrict gesture start position: only block if swipe starts within fixed edge area
                val screenWidth = resources.displayMetrics.widthPixels
                val screenHeight = resources.displayMetrics.heightPixels
                val startX = e1.x
                val startY = e1.y
                
                // Fixed edge threshold in dp (convert to pixels)
                val edgeThresholdDp = 48f
                val scale = resources.displayMetrics.density
                val edgeThresholdPx = (edgeThresholdDp * scale + 0.5f).toInt()
                
                // Block gesture if it starts within the fixed edge area from any screen edge
                if (startX <= edgeThresholdPx || 
                    startX >= screenWidth - edgeThresholdPx ||
                    startY <= edgeThresholdPx || 
                    startY >= screenHeight - edgeThresholdPx) {
                    return false
                }
                
                val player = mediaPlayer ?: return false

                isGesturing = true
                handler.removeCallbacks(hideGestureOverlayRunnable)
                gestureOverlay.animate().cancel()
                gestureOverlay.visibility = android.view.View.VISIBLE
                gestureOverlay.alpha = 1f
                
                // Determine gesture type based on direction and zoom state
                if (gestureType == null) {
                    if (currentZoomScale > 1f) {
                        // When zoomed in, allow pan gestures
                        gestureType = GestureType.PAN
                    } else if (kotlin.math.abs(distanceX) > kotlin.math.abs(distanceY)) {
                        // Horizontal swipe - seek
                        gestureType = GestureType.SEEK
                    } else {
                        // Vertical swipe - brightness or volume
                        gestureType = if (e1.x < screenWidth / 2) GestureType.BRIGHTNESS else GestureType.VOLUME
                    }
                }

                when (gestureType) {
                    GestureType.BRIGHTNESS -> {
                        brightnessIndicator.visibility = android.view.View.VISIBLE
                        volumeIndicator.visibility = android.view.View.INVISIBLE
                        seekIndicator.visibility = android.view.View.INVISIBLE
                        currentBrightness = (currentBrightness + (distanceY * 0.001f)).coerceIn(0f, 1f)
                        setBrightness(currentBrightness)
                        updateBrightnessIndicator()
                    }
                    GestureType.VOLUME -> {
                        volumeIndicator.visibility = android.view.View.VISIBLE
                        brightnessIndicator.visibility = android.view.View.INVISIBLE
                        seekIndicator.visibility = android.view.View.INVISIBLE
                        val volDelta = (distanceY * 0.001f * 100).toInt()
                        currentVolume = (currentVolume + volDelta).coerceIn(0, 100)
                        setVolume(currentVolume)
                        updateVolumeIndicator()
                    }
                    GestureType.PAN -> {
                        // Allow panning when zoomed in
                        currentTranslationX -= distanceX
                        currentTranslationY -= distanceY
                        applyVideoZoom()
                    }
                    GestureType.SEEK -> {
                        seekIndicator.visibility = android.view.View.VISIBLE
                        brightnessIndicator.visibility = android.view.View.INVISIBLE
                        volumeIndicator.visibility = android.view.View.INVISIBLE
                        
                        // If controls are hidden, show only the bottom (timeline) area
                        if (!isControlsVisible) {
                            playbackControls.visibility = android.view.View.VISIBLE
                            topControlsContainer.visibility = android.view.View.GONE
                            bottomControlsContainer.visibility = android.view.View.VISIBLE
                        } else {
                            // If already visible, keep them visible
                            resetControlsHideTimer()
                        }
                        
                        if (seekStartTime == -1L) {
                            seekStartTime = mediaPlayer?.time ?: -1L
                        }

                        // Calculate seek delta based on total horizontal swipe distance from start
                        val swipeDistance = e2.x - e1.x
                        // Sensitivity: proportional for short videos, capped at 3 min per full-width
                        // swipe for long videos so seeking never jumps wildly on movies/long content.
                        val maxSeekPerFullSwipe = 180_000L // 3 minutes in ms
                        val sensitivity = if (player.length > 0) {
                            minOf(
                                (player.length / screenWidth.toFloat()) * 0.25f,
                                maxSeekPerFullSwipe / screenWidth.toFloat()
                            )
                        } else 50f
                        seekDelta = (swipeDistance * sensitivity).toLong()
                        
                        val newTime = (seekStartTime + seekDelta).coerceIn(0L, player.length)
                        player.time = newTime
                        updateTimelineUi(newTime, player.length)
                        updateSeekIndicator()
                    }
                    else -> {}
                }
                return true
            }
        })

        scaleGestureDetector = android.view.ScaleGestureDetector(
            this,
            object : android.view.ScaleGestureDetector.SimpleOnScaleGestureListener() {
                override fun onScaleBegin(detector: android.view.ScaleGestureDetector): Boolean {
                    if (currentScreen != Screen.PLAYER) return false
                    blockSingleFingerGesturesUntilRelease = true
                    isGesturing = true
                    gestureType = null
                    handler.removeCallbacks(hideGestureOverlayRunnable)
                    gestureOverlay.animate().cancel()
                    gestureOverlay.visibility = android.view.View.VISIBLE
                    gestureOverlay.alpha = 1f
                    brightnessIndicator.visibility = android.view.View.INVISIBLE
                    volumeIndicator.visibility = android.view.View.INVISIBLE
                    seekIndicator.visibility = android.view.View.INVISIBLE
                    zoomIndicator.visibility = android.view.View.VISIBLE
                    updateZoomIndicator()
                    return true
                }

                override fun onScale(detector: android.view.ScaleGestureDetector): Boolean {
                    if (currentScreen != Screen.PLAYER) return false
                    // Natural pinch: pinch-in makes video smaller, pinch-out makes it larger.
                    currentZoomScale = (currentZoomScale * detector.scaleFactor).coerceIn(minZoomScale, maxZoomScale)
                    applyVideoZoom()
                    zoomIndicator.visibility = android.view.View.VISIBLE
                    updateZoomIndicator()
                    return true
                }

                override fun onScaleEnd(detector: android.view.ScaleGestureDetector) {
                    super.onScaleEnd(detector)
                    isGesturing = false
                    val currentVideo = if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) currentPlaylist[currentPlayingIndex] else null
                    currentVideo?.let { video ->
                        saveVideoZoomScale(video.path, currentZoomScale)
                    }
                    handler.postDelayed(hideGestureOverlayRunnable, 350)
                }
            }
        )
    }

    private fun handleGesture(event: android.view.MotionEvent): Boolean {
        if (currentScreen != Screen.PLAYER) return false
        
        if (isUiLocked) {
            when (event.actionMasked) {
                android.view.MotionEvent.ACTION_DOWN -> {
                    lastTouchX = event.x
                    lastTouchY = event.y
                    showLockIconForOneSec()
                    handler.postDelayed(unlockRunnable, 1000)
                }
                android.view.MotionEvent.ACTION_MOVE -> {
                    val deltaX = kotlin.math.abs(event.x - lastTouchX)
                    val deltaY = kotlin.math.abs(event.y - lastTouchY)
                    if (deltaX > TOUCH_SLOP || deltaY > TOUCH_SLOP) {
                        handler.removeCallbacks(unlockRunnable)
                    }
                }
                android.view.MotionEvent.ACTION_UP, android.view.MotionEvent.ACTION_CANCEL -> {
                    handler.removeCallbacks(unlockRunnable)
                }
            }
            return true
        }
        
        // Feed pinch detector only for genuine 2-finger sequences (or while already scaling).
        if (event.pointerCount >= 2 || scaleGestureDetector.isInProgress) {
            handler.removeCallbacks(lockRunnable)
            scaleGestureDetector.onTouchEvent(event)
            if (scaleGestureDetector.isInProgress) return true
        }

        // If a two-finger gesture just happened, ignore one-finger gestures until release.
        if (event.pointerCount >= 2) {
            blockSingleFingerGesturesUntilRelease = true
            handler.removeCallbacks(lockRunnable)
        }
        if (blockSingleFingerGesturesUntilRelease) {
            if (event.actionMasked == android.view.MotionEvent.ACTION_UP ||
                event.actionMasked == android.view.MotionEvent.ACTION_CANCEL
            ) {
                blockSingleFingerGesturesUntilRelease = false
                isGesturing = false
                gestureType = null
                seekDelta = 0L
                seekStartTime = -1L
                handler.postDelayed(hideGestureOverlayRunnable, 150)
            }
            return true
        }

        when (event.actionMasked) {
            android.view.MotionEvent.ACTION_DOWN -> {
                lastTouchX = event.x
                lastTouchY = event.y
                handler.postDelayed(lockRunnable, 1000)
            }
            android.view.MotionEvent.ACTION_MOVE -> {
                val deltaX = kotlin.math.abs(event.x - lastTouchX)
                val deltaY = kotlin.math.abs(event.y - lastTouchY)
                if (deltaX > TOUCH_SLOP || deltaY > TOUCH_SLOP) {
                    handler.removeCallbacks(lockRunnable)
                }
            }
            android.view.MotionEvent.ACTION_UP, android.view.MotionEvent.ACTION_CANCEL -> {
                handler.removeCallbacks(lockRunnable)
            }
        }

        gestureDetector.onTouchEvent(event)
        
        if (event.action == android.view.MotionEvent.ACTION_UP || event.action == android.view.MotionEvent.ACTION_CANCEL) {
            // Hide controls immediately if they were only shown for seeking
            if (gestureType == GestureType.SEEK && !isControlsVisible) {
                playbackControls.visibility = android.view.View.GONE
                topControlsContainer.visibility = android.view.View.VISIBLE
            }
            
            // Save translation when pan gesture ends
            if (gestureType == GestureType.PAN) {
                val currentVideo = if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) currentPlaylist[currentPlayingIndex] else null
                currentVideo?.let { video ->
                    saveVideoTranslation(video.path, currentTranslationX, currentTranslationY)
                }
            }
            
            gestureType = null
            seekDelta = 0L
            seekStartTime = -1L
            isGesturing = false
            handler.postDelayed(hideGestureOverlayRunnable, 200)
        }
        return true
    }
    
    private fun setBrightness(brightness: Float) {
        val layoutParams = window.attributes
        layoutParams.screenBrightness = brightness
        window.attributes = layoutParams
        
        // Save brightness preference
        sharedPrefs.edit().putFloat("saved_brightness", brightness).apply()
    }

    private fun resetToSystemBrightness() {
        val layoutParams = window.attributes
        layoutParams.screenBrightness = -1.0f // -1.0f tells the system to use its own brightness setting
        window.attributes = layoutParams
    }
    
    private fun setVolume(volume: Int) {
        val maxVolume = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val targetVolume = (maxVolume * volume + 50) / 100
        audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, targetVolume, 0)
        
        // Also set VLC volume
        mediaPlayer?.let { player ->
            player.volume = (volume * 256 / 100)
        }
        
        currentVolume = volume
        
        // Always save as default video volume so the next video remembers it
        sharedPrefs.edit().putInt("saved_volume", volume).apply()
        
        // Save volume for current video specifically if playing
        if (currentScreen == Screen.PLAYER && currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
            val currentVideo = currentPlaylist[currentPlayingIndex]
            saveVideoVolume(currentVideo.path, volume)
        }
    }
    
    private fun updateBrightnessIndicator() {
        tvBrightnessPercent.text = "${(currentBrightness * 100).toInt()}%"
        brightnessProgressBar.progress = (currentBrightness * 100).toInt()
    }
    
    private fun updateVolumeIndicator() {
        tvVolumePercent.text = "$currentVolume%"
        volumeProgressBar.progress = currentVolume
    }

    private fun applyVideoZoom() {
        // Ensure the view is laid out before applying zoom
        if (vlcVideoLayout.width > 0 && vlcVideoLayout.height > 0) {
            vlcVideoLayout.pivotX = vlcVideoLayout.width / 2f
            vlcVideoLayout.pivotY = vlcVideoLayout.height / 2f
            vlcVideoLayout.scaleX = currentZoomScale
            vlcVideoLayout.scaleY = currentZoomScale
            // Apply saved translation
            vlcVideoLayout.translationX = currentTranslationX
            vlcVideoLayout.translationY = currentTranslationY
        } else {
            // Wait for layout if dimensions are not ready
            vlcVideoLayout.viewTreeObserver.addOnGlobalLayoutListener(object : android.view.ViewTreeObserver.OnGlobalLayoutListener {
                override fun onGlobalLayout() {
                    if (vlcVideoLayout.width > 0 && vlcVideoLayout.height > 0) {
                        vlcVideoLayout.viewTreeObserver.removeOnGlobalLayoutListener(this)
                        vlcVideoLayout.pivotX = vlcVideoLayout.width / 2f
                        vlcVideoLayout.pivotY = vlcVideoLayout.height / 2f
                        vlcVideoLayout.scaleX = currentZoomScale
                        vlcVideoLayout.scaleY = currentZoomScale
                        vlcVideoLayout.translationX = currentTranslationX
                        vlcVideoLayout.translationY = currentTranslationY
                    }
                }
            })
        }
    }

    private fun updateZoomIndicator() {
        val zoomPercent = (currentZoomScale * 100).toInt()
        tvZoomPercent.text = "$zoomPercent%"
    }

    private fun selectSubtitleTrackVlcStyle(trackId: Int, trackName: String?) {
        pendingSubtitleTrackId = trackId
        pendingSubtitleTrackName = trackName
        mediaPlayer?.let { tryApplyPendingSubtitleTrack(it) }
    }

    private fun resolveSubtitleTrackId(player: MediaPlayer, requestedId: Int, requestedName: String?): Int {
        val tracks = player.spuTracks ?: return requestedId
        if (tracks.any { it.id == requestedId }) return requestedId
        if (!requestedName.isNullOrBlank()) {
            tracks.firstOrNull { it.name == requestedName }?.let { return it.id }
        }
        // Fallback to first non-disabled subtitle track if available.
        return tracks.firstOrNull { it.id != -1 }?.id ?: requestedId
    }

    private fun tryApplyPendingSubtitleTrack(player: MediaPlayer) {
        val requestedId = pendingSubtitleTrackId ?: return
        val requestedName = pendingSubtitleTrackName
        val resolvedId = resolveSubtitleTrackId(player, requestedId, requestedName)
        player.spuTrack = resolvedId
        if (player.spuTrack == resolvedId) {
            pendingSubtitleTrackId = null
            pendingSubtitleTrackName = null
        }
    }

    private fun applySubtitleTrackReliably(
        player: MediaPlayer,
        requestedId: Int,
        requestedName: String?,
        onComplete: (() -> Unit)? = null
    ) {
        pendingSubtitleTrackId = requestedId
        pendingSubtitleTrackName = requestedName
        val maxAttempts = 6
        val retryDelayMs = 180L

        fun attempt(tryIndex: Int) {
            if (mediaPlayer !== player) return
            val resolvedId = resolveSubtitleTrackId(player, requestedId, requestedName)
            player.spuTrack = resolvedId

            handler.postDelayed({
                if (mediaPlayer !== player) return@postDelayed
                if (player.spuTrack == resolvedId) {
                    pendingSubtitleTrackId = null
                    pendingSubtitleTrackName = null
                    onComplete?.invoke()
                    return@postDelayed
                }

                if (tryIndex >= maxAttempts - 1) {
                    // Final best effort: force-disable then force-select again.
                    player.spuTrack = -1
                    handler.postDelayed({
                        if (mediaPlayer !== player) return@postDelayed
                        player.spuTrack = resolvedId
                        handler.postDelayed({
                            if (mediaPlayer === player && player.spuTrack == resolvedId) {
                                pendingSubtitleTrackId = null
                                pendingSubtitleTrackName = null
                            }
                            onComplete?.invoke()
                        }, 120)
                    }, 120)
                    return@postDelayed
                }

                attempt(tryIndex + 1)
            }, retryDelayMs)
        }

        attempt(0)
    }

    private fun updateTimelineUi(time: Long, length: Long) {
        if (length <= 0) return
        tvTotalTime.text = formatTime(length)
        tvCurrentTime.text = formatTime(time)
        if (!seekBar.isPressed) {
            seekBar.progress = (time * 1000 / length).toInt()
        }
    }
    
    private fun showTrackSelectionBottomSheet(
        title: String,
        tracks: Array<out MediaPlayer.TrackDescription>?,
        currentTrackId: Int,
        player: MediaPlayer,
        wasPlayingBeforeOpen: Boolean,
        onSelected: (Int) -> Unit
    ) {
        val dialog = com.google.android.material.bottomsheet.BottomSheetDialog(this, R.style.ModernBottomSheetDialogTheme)
        val view = layoutInflater.inflate(R.layout.dialog_track_selection, null)
        var selectionMade = false
        
        val tvTitle = view.findViewById<android.widget.TextView>(R.id.tvDialogTitle)
        val listView = view.findViewById<android.widget.ListView>(R.id.trackListView)
        
        tvTitle.text = title
        
        val trackNames = if (tracks == null || tracks.isEmpty()) {
            arrayOf("No tracks available")
        } else {
            tracks.map { it.name }.toTypedArray()
        }
        val adapter = android.widget.ArrayAdapter(this, R.layout.item_track, trackNames)
        listView.adapter = adapter
        listView.choiceMode = android.widget.ListView.CHOICE_MODE_SINGLE
        
        // Find current track index
        val currentIndex = if (tracks != null && tracks.isNotEmpty()) {
            tracks.indexOfFirst { it.id == currentTrackId }
        } else {
            -1
        }
        if (currentIndex != -1) {
            listView.setItemChecked(currentIndex, true)
        }
        
        listView.setOnItemClickListener { _, _, position, _ ->
            if (tracks == null || tracks.isEmpty()) {
                dialog.dismiss()
                return@setOnItemClickListener
            }
            
            selectionMade = true
            val selectedId = tracks[position].id
            val resumePlayback = {
                if (wasPlayingBeforeOpen && mediaPlayer === player) {
                    player.play()
                    resetControlsHideTimer()
                }
            }
            if (title == "Subtitle tracks" && mediaPlayer === player) {
                val selectedTrackName = tracks[position].name
                applySubtitleTrackReliably(
                    player = player,
                    requestedId = selectedId,
                    requestedName = selectedTrackName,
                    onComplete = resumePlayback
                )
                onSelected(selectedId)
            } else {
                onSelected(selectedId)
                if (wasPlayingBeforeOpen && mediaPlayer === player) {
                    handler.postDelayed({
                        if (mediaPlayer === player) {
                            player.play()
                            resetControlsHideTimer()
                        }
                    }, 200)
                }
            }
            dialog.dismiss()
        }

        dialog.setOnDismissListener {
            if (!selectionMade && wasPlayingBeforeOpen && mediaPlayer === player) {
                player.play()
                resetControlsHideTimer()
            }
        }
        
        dialog.setContentView(view)
        
        // Force the bottom sheet to open at full height
        dialog.behavior.state = com.google.android.material.bottomsheet.BottomSheetBehavior.STATE_EXPANDED
        dialog.behavior.skipCollapsed = true
        
        dialog.show()
    }
    
    private fun updateSeekIndicator() {
        val player = mediaPlayer ?: return
        
        val currentTime = player.time
        tvSeekTime.text = formatTime(currentTime)
        
        // Calculate effective delta based on actual player time vs start time
        val effectiveDelta = if (seekStartTime != -1L) currentTime - seekStartTime else 0L
        val absDelta = kotlin.math.abs(effectiveDelta)
        
        if (effectiveDelta >= 0) {
            tvSeekOffset.text = "+${formatTime(absDelta)}"
            tvSeekOffset.setTextColor(android.graphics.Color.GREEN)
        } else {
            tvSeekOffset.text = "-${formatTime(absDelta)}"
            tvSeekOffset.setTextColor(android.graphics.Color.RED)
        }
    }
    

    private fun findCandidateSubtitleFiles(videoPath: String): List<File> {
        val videoFile = File(videoPath)
        val parent = videoFile.parentFile ?: return emptyList()
        val videoBaseName = videoFile.nameWithoutExtension.lowercase(Locale.ROOT)
        val candidates = parent.listFiles()?.filter { candidate ->
            if (!candidate.isFile) return@filter false
            val extension = candidate.extension.lowercase(Locale.ROOT)
            if (extension !in SUBTITLE_EXTENSIONS) return@filter false
            val subtitleBaseName = candidate.nameWithoutExtension.lowercase(Locale.ROOT)
            subtitleBaseName == videoBaseName ||
                subtitleBaseName.startsWith("$videoBaseName.") ||
                subtitleBaseName.startsWith("$videoBaseName ")
        } ?: emptyList()
        return candidates.sortedBy { it.name.lowercase(Locale.ROOT) }
    }

    private fun attachExternalSubtitlesLikeVlc(player: MediaPlayer, videoPath: String) {
        val subtitleFiles = findCandidateSubtitleFiles(videoPath)
        if (subtitleFiles.isEmpty()) return
        subtitleFiles.forEach { subtitleFile ->
            try {
                player.addSlave(IMedia.Slave.Type.Subtitle, subtitleFile.absolutePath, false)
            } catch (e: Exception) {
                android.util.Log.w(
                    "OniPlayer",
                    "Failed to attach subtitle file: ${subtitleFile.absolutePath}",
                    e
                )
            }
        }
    }

    private fun showFolderList() {
        // Set screen state first so exitFullScreen knows we're leaving player
        currentScreen = Screen.FOLDERS
        exitFullScreen()
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        title = "OniPlayer"
        supportActionBar?.show()
        supportActionBar?.setDisplayHomeAsUpEnabled(false)
        supportActionBar?.setHomeButtonEnabled(false)

        if (folders.isEmpty()) {
            // Show no videos message but keep swipe refresh enabled
            folderRecyclerView.visibility = android.view.View.GONE
            videoRecyclerView.visibility  = android.view.View.GONE
            playerContainer.visibility    = android.view.View.GONE
            noVideosLayout.visibility     = android.view.View.VISIBLE
            folderSwipeRefresh.visibility = android.view.View.VISIBLE
            videoSwipeRefresh.visibility = android.view.View.GONE
        } else {
            // Show folders
            folderRecyclerView.adapter = FolderAdapter(
                folders = folders,
                onFolderClick = { folder ->
                    // Cancel refresh if in progress
                    cancelRefresh()
                    
                    if (!isMultiSelectMode) {
                        showVideoListForFolder(folder)
                    }
                },
                onFolderLongClick = { folder ->
                    enterMultiSelectMode()
                    toggleFolderSelection(folder.path ?: "")
                    updateFolderAdapter()
                },
                isMultiSelectMode = isMultiSelectMode,
                selectedFolders = selectedFolders,
                onSelectionToggle = { folderPath ->
                    toggleFolderSelection(folderPath)
                    updateFolderAdapter()
                }
            )

            folderRecyclerView.visibility = android.view.View.VISIBLE
            videoRecyclerView.visibility  = android.view.View.GONE
            playerContainer.visibility    = android.view.View.GONE
            noVideosLayout.visibility     = android.view.View.GONE
            
            // Show folder swipe refresh, hide video swipe refresh
            folderSwipeRefresh.visibility = android.view.View.VISIBLE
            videoSwipeRefresh.visibility = android.view.View.GONE
        }

    }

    private fun showVideoListForFolder(folder: FolderItem) {
        currentScreen = Screen.VIDEOS
        currentFolderName = folder.name
        currentFolderPath = folder.path
        title = currentFolderName
        supportActionBar?.show()
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.setHomeButtonEnabled(true)

        // Reset scroll position when entering a new folder
        savedVideoListScrollPosition = 0

        currentPlaylist = folder.videos

        videoRecyclerView.adapter = VideoAdapter(
                videos = folder.videos,
                sharedPrefs = sharedPrefs,
                onVideoClick = { video ->
                    if (!isMultiSelectMode) {
                        // Save current scroll position before playing video
                        val layoutManager = videoRecyclerView.layoutManager as LinearLayoutManager
                        savedVideoListScrollPosition = layoutManager.findFirstVisibleItemPosition()
                        
                        currentPlayingIndex = folder.videos.indexOf(video)
                        playVideo(video)
                    }
                },
                onVideoLongClick = { video ->
                    enterMultiSelectMode()
                    toggleVideoSelection(video.path ?: "")
                    updateVideoAdapter()
                },
                isMultiSelectMode = isMultiSelectMode,
                selectedVideos = selectedVideos,
                onSelectionToggle = { videoPath ->
                    toggleVideoSelection(videoPath)
                    updateVideoAdapter()
                }
            )

        folderRecyclerView.visibility = android.view.View.GONE
        videoRecyclerView.visibility  = android.view.View.VISIBLE
        playerContainer.visibility    = android.view.View.GONE
        noVideosLayout.visibility     = android.view.View.GONE
        
        // Show video swipe refresh, hide folder swipe refresh
        folderSwipeRefresh.visibility = android.view.View.GONE
        videoSwipeRefresh.visibility = android.view.View.VISIBLE

    }

    private fun showVideoList() {
        // Set screen state first so exitFullScreen knows we're leaving player
        currentScreen = Screen.VIDEOS
        exitFullScreen()
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        title = currentFolderName
        supportActionBar?.show()
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.setHomeButtonEnabled(true)
        // Refresh the adapter to show updated progress/watched status
        videoRecyclerView.adapter?.notifyDataSetChanged()
        
        // Show video swipe refresh, hide folder swipe refresh
        folderSwipeRefresh.visibility = android.view.View.GONE
        videoSwipeRefresh.visibility = android.view.View.VISIBLE

        folderRecyclerView.visibility = android.view.View.GONE
        videoRecyclerView.visibility  = android.view.View.VISIBLE
        playerContainer.visibility    = android.view.View.GONE
        noVideosLayout.visibility     = android.view.View.GONE
        
        // Restore saved scroll position after refreshing
        val layoutManager = videoRecyclerView.layoutManager as LinearLayoutManager
        videoRecyclerView.post {
            layoutManager.scrollToPositionWithOffset(savedVideoListScrollPosition, 0)
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        // Cancel refresh if in progress
        cancelRefresh()
        
        return when (currentScreen) {
            Screen.VIDEOS -> {
                showFolderList()
                true
            }
            Screen.PLAYER -> {
                stopVideo()
                showVideoList()
                true
            }
            Screen.FOLDERS -> super.onSupportNavigateUp()
        }
    }

    // ── Playback ───────────────────────────────────────────────────────────
    private fun playVideo(video: VideoItem) {
        try {
            // Check if video file exists before attempting to play
            val videoFile = File(video.path)
            if (!videoFile.exists()) {
                Toast.makeText(this, "Video file not found: ${video.title}", Toast.LENGTH_LONG).show()
                android.util.Log.e("OniPlayer", "Video file not found: ${video.path}")
                return
            }
            
            if (isGesturing) {
                blockSingleFingerGesturesUntilRelease = true
            }
            
            stopVideo()
            
            // Reset background state when starting new video
            isInBackground = false
            currentVideoPath = video.path
            currentVideoPosition = 0L
            wasPlayingBeforeBackground = false

            // Force the Android display video output module so video always renders
            val options = arrayListOf(
                "--aout=audiotrack",
                "--audio-time-stretch",
                "--rtsp-tcp"
            )

            libVLC = LibVLC(this, options)
            val player = MediaPlayer(libVLC)
            mediaPlayer = player

            // VLCVideoLayout handles all surface lifecycle internally.
            // Third param = enableSubtitles (true required for SPU track rendering)
            player.attachViews(vlcVideoLayout, null, true, false)

            val media = Media(libVLC, video.path)
            // Keep hardware decoding enabled, but disable direct rendering like VLC's
            // decoding-only mode to improve subtitle blending compatibility.
            media.setHWDecoderEnabled(true, true)
            media.addOption(":no-mediacodec-dr")
            media.addOption(":no-omxil-dr")
            player.media = media
            media.release() 
            attachExternalSubtitlesLikeVlc(player, video.path)
            
            // Store current system volume before changing it (only if we're coming from outside player)
            if (currentScreen != Screen.PLAYER) {
                val currentVolIndex = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
                val maxVol = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                
                // Save raw index for accurate restoration
                sharedPrefs.edit().putInt(PREF_ORIGINAL_SYSTEM_VOLUME, currentVolIndex).apply()
                
                // Also update our percentage variable
                systemVolume = if (maxVol > 0) (currentVolIndex * 100 / maxVol) else 70
            }
            
            // Load saved volume for this specific video
            currentVolume = getVideoVolume(video.path)
            
            // Load saved zoom scale for this specific video
            currentZoomScale = getVideoZoomScale(video.path)
            
            // Load saved translation for this specific video
            val (savedTranslationX, savedTranslationY) = getVideoTranslation(video.path)
            currentTranslationX = savedTranslationX
            currentTranslationY = savedTranslationY
            
            // Load saved subtitle track for this specific video
            val savedSpuId = sharedPrefs.getInt("subtitle_track_id_${video.path}", -999)
            if (savedSpuId != -999) {
                pendingSubtitleTrackId = savedSpuId
                pendingSubtitleTrackName = sharedPrefs.getString("subtitle_track_name_${video.path}", null)
            } else {
                pendingSubtitleTrackId = null
                pendingSubtitleTrackName = null
            }
            
            // Load saved audio track for this specific video
            val savedAudioId = sharedPrefs.getInt("audio_track_id_${video.path}", -999)
            if (savedAudioId != -999) {
                pendingAudioTrackId = savedAudioId
                pendingAudioTrackName = sharedPrefs.getString("audio_track_name_${video.path}", null)
            } else {
                pendingAudioTrackId = null
                pendingAudioTrackName = null
            }
            
            // Reset completion flag for new video
            videoMarkedAsCompleted = false
            
            // Restore saved progress so the player can seek to it once playback starts
            val actualSavedProgress = getVideoProgress(video.path)
            pendingVideoDuration = video.duration
            // COMPLETED_SENTINEL (Long.MAX_VALUE) means the video was watched fully —
            // seek back to the start so VLC doesn't linger at the end position and
            // immediately fire EndReached again when the player starts.
            val wasCompleted = actualSavedProgress == Long.MAX_VALUE
            val nearEnd = !wasCompleted && pendingVideoDuration > 0 && actualSavedProgress >= pendingVideoDuration
            // When the video is fully watched we must EXPLICITLY seek to 0; we store -1
            // as the sentinel so the Playing handler always performs the seek.
            pendingSavedProgress = when {
                wasCompleted || nearEnd -> -1L  // -1 = "seek to start"
                else -> actualSavedProgress
            }
            android.util.Log.d("OniPlayer", "Video start: saved=${formatTime(actualSavedProgress)}, resuming from=${formatTime(pendingSavedProgress)} wasCompleted=$wasCompleted")

            // Show/hide continue from position button based on saved progress
            updateContinueFromPositionButton(video.path, video.duration)
            
            // Set saved brightness
            setBrightness(currentBrightness)
            
            // Set video-specific volume
            val maxVolume = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
            val targetVolume = (maxVolume * currentVolume + 50) / 100
            audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, targetVolume, 0)
            
            // Also set VLC volume
            mediaPlayer?.let { player ->
                player.volume = (currentVolume * 256 / 100)
            }
            // Apply zoom after layout is ready
            vlcVideoLayout.post {
                applyVideoZoom()
            }
            updateZoomIndicator()

            // Add timeout to detect if video fails to start playing (corrupted/unsupported files)
            var videoStarted = false
            handler.postDelayed({
                if (!videoStarted && currentScreen == Screen.PLAYER && mediaPlayer === player) {
                    android.util.Log.e("OniPlayer", "Video failed to start playing (timeout): ${video.path}")
                    runOnUiThread {
                        Toast.makeText(this@MainActivity, "Unable to play video: ${video.title}", Toast.LENGTH_LONG).show()
                        stopVideo()
                        showVideoList()
                    }
                }
            }, 5000) // 5 second timeout

            val listener = MediaPlayer.EventListener { event ->
                runOnUiThread {
                    if (currentScreen != Screen.PLAYER) return@runOnUiThread
                    val activePlayer = mediaPlayer ?: return@runOnUiThread
                    
                    when (event.type) {
                        MediaPlayer.Event.Playing -> {
                            videoStarted = true // Mark video as started to cancel timeout
                            btnPlayPause.setImageResource(R.drawable.ic_pause)
                            // Keep the screen on while video is actively playing
                            window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                            val spuId = pendingSubtitleTrackId
                            if (spuId != null) {
                                applySubtitleTrackReliably(activePlayer, spuId, pendingSubtitleTrackName)
                            }
                            tryApplyPendingAudioTrack(activePlayer)
                            resetControlsHideTimer()
                            
                            // Re-apply zoom and translation after a short delay to ensure VLC has finished setting up the surface
                            handler.postDelayed({
                                applyVideoZoom()
                            }, 100)
                            
                            // Seek to the saved position as soon as playback begins.
                            // pendingSavedProgress == -1L means "restart from the beginning"
                            // (video was previously completed), so we explicitly seek to 0
                            // to prevent VLC from staying at its last position and immediately
                            // re-firing EndReached.
                            if (pendingSavedProgress == -1L) {
                                android.util.Log.d("OniPlayer", "Restarting completed video from position 0")
                                activePlayer.time = 0L
                                pendingSavedProgress = 0L
                                // IMPORTANT: clear the Long.MAX_VALUE "watched" sentinel now that
                                // the user has chosen to rewatch. From this point on, progress
                                // saves must work normally so the rewatch position is preserved.
                                // The watched badge will return once they finish watching again.
                                val rewatchPath = currentPlaylist.getOrNull(currentPlayingIndex)?.path
                                if (!rewatchPath.isNullOrEmpty()) {
                                    sharedPrefs.edit().remove("progress_$rewatchPath").apply()
                                }
                            } else if (pendingSavedProgress > 0) {
                                android.util.Log.d("OniPlayer", "Resuming from: ${formatTime(pendingSavedProgress)}")
                                activePlayer.time = pendingSavedProgress
                                pendingSavedProgress = 0L // clear so it doesn't fire again
                            }
                        }
                        MediaPlayer.Event.Paused -> {
                            btnPlayPause.setImageResource(R.drawable.ic_play)
                            handler.removeCallbacks(hideControlsRunnable)
                            
                            // Save progress on pause, but never overwrite the "watched" sentinel
                            if (!videoMarkedAsCompleted && currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
                                val currentVideo = currentPlaylist[currentPlayingIndex]
                                mediaPlayer?.let { player ->
                                    saveVideoProgress(currentVideo.path, player.time)
                                }
                            }
                        }
                        MediaPlayer.Event.ESAdded -> {
                            // VLC discovered a new elementary stream (audio/video/subtitle).
                            // Apply pending subtitle again when subtitle streams become available.
                            tryApplyPendingAudioTrack(activePlayer)
                        }
                        MediaPlayer.Event.TimeChanged -> {
                            val length = activePlayer.length
                            val time = activePlayer.time
                            updateTimelineUi(time, length)
                            
                            // Save progress periodically, but never after the video is marked watched
                            if (!videoMarkedAsCompleted && time % 5000 < 100 && currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
                                val currentVideo = currentPlaylist[currentPlayingIndex]
                                saveVideoProgress(currentVideo.path, time)
                            }
                            
                            // Mark as watched when video reaches 100%
                            if (!videoMarkedAsCompleted && length > 0 && time >= length) {
                                if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
                                    val currentVideo = currentPlaylist[currentPlayingIndex]
                                    markVideoAsWatched(currentVideo.path)
                                    videoMarkedAsCompleted = true
                                }
                            }
                        }
                        MediaPlayer.Event.EndReached -> {
                            // Allow screen to turn off once playback ends
                            window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                            // Save progress when video naturally ends.
                            // Use Long.MAX_VALUE as a "fully watched" sentinel so the watched
                            // badge always appears reliably — even when video.duration is 0 or
                            // inaccurate (MediaStore values can be stale).
                            if (!videoMarkedAsCompleted && currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
                                val currentVideo = currentPlaylist[currentPlayingIndex]
                                markVideoAsWatched(currentVideo.path)
                                videoMarkedAsCompleted = true
                            }
                            playNextVideo()
                        }
                        MediaPlayer.Event.EncounteredError -> {
                            // Handle VLC playback errors
                            android.util.Log.e("OniPlayer", "VLC encountered error playing video: ${video.path}")
                            // Allow screen to turn off on error
                            window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                            runOnUiThread {
                                Toast.makeText(this@MainActivity, "Error playing video: ${video.title}", Toast.LENGTH_LONG).show()
                                stopVideo()
                                showVideoList()
                            }
                        }
                    }
                }
            }
            player.setEventListener(listener)
            
            player.play()

            val savedOrientation = sharedPrefs.getInt("video_orientation", ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE)
            requestedOrientation = savedOrientation

            enterFullScreen()

            currentScreen = Screen.PLAYER
            title = video.title
            tvVideoTitle.text = video.title
            supportActionBar?.hide()
            
            folderRecyclerView.visibility = android.view.View.GONE
            videoRecyclerView.visibility  = android.view.View.GONE
            playerContainer.visibility    = android.view.View.VISIBLE
            
            playbackControls.visibility = android.view.View.VISIBLE
            isControlsVisible = true
            resetControlsHideTimer()

        } catch (e: Exception) {
            e.printStackTrace()
            android.util.Log.e("OniPlayer", "playVideo error: ${e.message}", e)
            Toast.makeText(this, "Error: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun playNextVideo() {
        if (currentPlaylist.isNotEmpty() && currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size - 1) {
            // Save current video progress NOW, before changing the index — BUT only if the
            // video hasn't already been marked as watched. If it has, we must not overwrite
            // the Long.MAX_VALUE sentinel with the raw end-of-file timestamp.
            if (!videoMarkedAsCompleted) {
                mediaPlayer?.let { player ->
                    val currentVideo = currentPlaylist[currentPlayingIndex]
                    saveVideoProgress(currentVideo.path, player.time)
                }
            }
            currentPlayingIndex++
            playVideo(currentPlaylist[currentPlayingIndex])
        } else {
            stopVideo()
            showVideoList()
        }
    }

    private fun playPreviousVideo() {
        if (currentPlaylist.isNotEmpty() && currentPlayingIndex > 0) {
            // Save current video progress before decrementing index (same reason as playNextVideo).
            mediaPlayer?.let { player ->
                val currentVideo = currentPlaylist[currentPlayingIndex]
                saveVideoProgress(currentVideo.path, player.time)
            }
            currentPlayingIndex--
            playVideo(currentPlaylist[currentPlayingIndex])
        } else {
            // If at first video, just restart it
            mediaPlayer?.time = 0L
        }
    }

    private fun stopVideo() {
        try {
            // Hide continue from position button when stopping video
            btnContinueFromPosition.visibility = android.view.View.GONE
            isUiLocked = false
            handler.removeCallbacks(hideLockIconRunnable)
            if (::btnLockScreen.isInitialized) {
                btnLockScreen.visibility = android.view.View.GONE
            }
            // Allow screen to turn off once video is stopped
            window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            resetToSystemBrightness()
            // Restore system volume if we are actually exiting the player screen
            if (currentScreen != Screen.PLAYER) {
                restoreSystemVolume()
            }
            mediaPlayer?.let { player ->
                // Save progress before stopping.
                // IMPORTANT: use currentVideoPath, NOT currentPlaylist[currentPlayingIndex].
                // When called from playVideo() via playNextVideo/playPreviousVideo the index has
                // already been incremented to the next video, so indexing into the playlist would
                // write the old video's position into the next video's progress key.
                // currentVideoPath is still the path of the video that was actually playing
                // because playVideo() only updates it AFTER stopVideo() returns.
                // Also: never overwrite the Long.MAX_VALUE "watched" sentinel.
                val pathToSave = currentVideoPath
                if (!pathToSave.isNullOrEmpty()) {
                    if (!videoMarkedAsCompleted) {
                        saveVideoProgress(pathToSave, player.time)
                    }
                    saveVideoTranslation(pathToSave, currentTranslationX, currentTranslationY)
                }
                player.stop()
                player.detachViews()
                player.release()
            }

            mediaPlayer = null
            
            libVLC?.release()
            libVLC = null
            
            // Reset background state when completely stopping video
            isInBackground = false
            currentVideoPath = null
            currentVideoPosition = 0L
            wasPlayingBeforeBackground = false
            // Reset translation for next video
            currentTranslationX = 0f
            currentTranslationY = 0f
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun enterFullScreen() {
        androidx.core.view.WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = android.graphics.Color.TRANSPARENT
        window.navigationBarColor = android.graphics.Color.TRANSPARENT
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) {
            val params = window.attributes
            params.layoutInDisplayCutoutMode = android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            window.attributes = params
        }
        androidx.core.view.WindowInsetsControllerCompat(window, window.decorView).let { controller ->
            controller.hide(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            controller.systemBarsBehavior = androidx.core.view.WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    private fun markVideoAsWatched(path: String) {
        android.util.Log.d("OniPlayer", "Marking video as watched: $path")
        // Long.MAX_VALUE is the "fully watched" sentinel recognised by VideoAdapter
        sharedPrefs.edit().putLong("progress_$path", Long.MAX_VALUE).apply()
    }

    private fun saveVideoProgress(path: String, time: Long) {
        if (time <= 0) return
        android.util.Log.d("OniPlayer", "Saving progress: $path at ${formatTime(time)}")
        sharedPrefs.edit().putLong("progress_$path", time).apply()
        
        // Update continue button visibility if this is the current video
        if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
            val currentVideo = currentPlaylist[currentPlayingIndex]
            if (currentVideo.path == path) {
                updateContinueFromPositionButton(path, currentVideo.duration)
            }
        }
    }

    private fun getVideoProgress(path: String): Long {
        val progress = sharedPrefs.getLong("progress_$path", 0L)
        android.util.Log.d("OniPlayer", "Getting progress: $path -> ${formatTime(progress)}")
        return progress
    }

    private fun updateContinueFromPositionButton(videoPath: String, videoDuration: Long) {
        val savedProgress = getVideoProgress(videoPath)
        if (savedProgress > 0 && savedProgress < videoDuration) {
            btnContinueFromPosition.visibility = android.view.View.GONE
        } else {
            btnContinueFromPosition.visibility = android.view.View.GONE
        }
    }

    private fun clearAllVideoProgress() {
        val editor = sharedPrefs.edit()
        val allKeys = sharedPrefs.all.keys
        allKeys.filter { it.startsWith("progress_") }.forEach { key ->
            editor.remove(key)
        }
        editor.apply()
        android.util.Log.d("OniPlayer", "Cleared all saved video progress")
    }

    private fun exitFullScreen() {

        androidx.core.view.WindowCompat.setDecorFitsSystemWindows(window, true)
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) {
            val params = window.attributes
            params.layoutInDisplayCutoutMode = android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_DEFAULT
            window.attributes = params
        }
        androidx.core.view.WindowInsetsControllerCompat(window, window.decorView).show(androidx.core.view.WindowInsetsCompat.Type.systemBars())
        resetToSystemBrightness()
        // Only restore system volume when exiting to folder/video list, not when just closing video
        if (currentScreen != Screen.PLAYER) {
            restoreSystemVolume()
        }
    }
    
    private fun restoreSystemVolume() {
        val originalVolIndex = sharedPrefs.getInt(PREF_ORIGINAL_SYSTEM_VOLUME, -1)
        if (originalVolIndex != -1) {
            audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, originalVolIndex, 0)
            sharedPrefs.edit().remove(PREF_ORIGINAL_SYSTEM_VOLUME).apply()
            
            // Update local percentage variable to match restored volume
            val maxVol = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
            systemVolume = if (maxVol > 0) (originalVolIndex * 100 / maxVol) else 70
        }
    }
    
    private fun saveVideoVolume(path: String, volume: Int) {
        sharedPrefs.edit().putInt("volume_$path", volume).apply()
    }
    
    private fun getVideoVolume(path: String): Int {
        return sharedPrefs.getInt("volume_$path", -1).let { saved ->
            if (saved != -1) saved else sharedPrefs.getInt("saved_volume", systemVolume)
        }
    }

    private fun saveVideoAudioTrack(path: String, trackId: Int, trackName: String?) {
        sharedPrefs.edit()
            .putInt("audio_track_id_$path", trackId)
            .putString("audio_track_name_$path", trackName)
            .apply()
        android.util.Log.d("OniPlayer", "Saved audio track for $path: id=$trackId, name=$trackName")
    }

    private fun saveVideoSubtitleTrack(path: String, trackId: Int, trackName: String?) {
        sharedPrefs.edit()
            .putInt("subtitle_track_id_$path", trackId)
            .putString("subtitle_track_name_$path", trackName)
            .apply()
        android.util.Log.d("OniPlayer", "Saved subtitle track for $path: id=$trackId, name=$trackName")
    }

    private fun saveVideoZoomScale(path: String, scale: Float) {
        sharedPrefs.edit().putFloat("zoom_scale_$path", scale).apply()
        android.util.Log.d("OniPlayer", "Saved zoom scale for $path: $scale")
    }

    private fun getVideoZoomScale(path: String): Float {
        val scale = sharedPrefs.getFloat("zoom_scale_$path", 1.0f)
        android.util.Log.d("OniPlayer", "Loaded zoom scale for $path: $scale")
        return scale
    }

    private fun saveVideoTranslation(path: String, translationX: Float, translationY: Float) {
        sharedPrefs.edit()
            .putFloat("translation_x_$path", translationX)
            .putFloat("translation_y_$path", translationY)
            .apply()
        android.util.Log.d("OniPlayer", "Saved translation for $path: x=$translationX, y=$translationY")
    }

    private fun getVideoTranslation(path: String): Pair<Float, Float> {
        val translationX = sharedPrefs.getFloat("translation_x_$path", 0f)
        val translationY = sharedPrefs.getFloat("translation_y_$path", 0f)
        android.util.Log.d("OniPlayer", "Loaded translation for $path: x=$translationX, y=$translationY")
        return Pair(translationX, translationY)
    }

    private fun resolveAudioTrackId(player: MediaPlayer, requestedId: Int, requestedName: String?): Int {
        val tracks = player.audioTracks ?: return requestedId
        if (tracks.any { it.id == requestedId }) return requestedId
        if (!requestedName.isNullOrBlank()) {
            tracks.firstOrNull { it.name == requestedName }?.let { return it.id }
        }
        return requestedId
    }

    private fun tryApplyPendingAudioTrack(player: MediaPlayer) {
        val requestedId = pendingAudioTrackId ?: return
        val requestedName = pendingAudioTrackName
        val resolvedId = resolveAudioTrackId(player, requestedId, requestedName)
        player.audioTrack = resolvedId
        if (player.audioTrack == resolvedId) {
            pendingAudioTrackId = null
            pendingAudioTrackName = null
            android.util.Log.d("OniPlayer", "Successfully applied pending audio track: $resolvedId")
        }
    }

    // ── Lifecycle management ────────────────────────────────────────────────
    override fun onPause() {
        super.onPause()
        if (currentScreen == Screen.PLAYER && mediaPlayer != null) {
            // Save current video state
            wasPlayingBeforeBackground = mediaPlayer?.isPlaying == true
            currentVideoPath = currentPlaylist.getOrNull(currentPlayingIndex)?.path
            currentVideoPosition = mediaPlayer?.time ?: 0L
            isInBackground = true
            
            // Don't save progress when going to background
            // if (currentPlayingIndex != -1 && currentPlayingIndex < currentPlaylist.size) {
            //     val currentVideo = currentPlaylist[currentPlayingIndex]
            //     mediaPlayer?.let { player ->
            //         saveVideoProgress(currentVideo.path, player.time)
            //     }
            // }
            
            // Pause but don't release the player
            mediaPlayer?.pause()
        }
    }
    
    override fun onResume() {
        super.onResume()
        
        // Check if permission was granted when returning from settings
        val permission = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU)
            Manifest.permission.READ_MEDIA_VIDEO
        else
            Manifest.permission.READ_EXTERNAL_STORAGE

        val permissionStorage = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R)
            Manifest.permission.MANAGE_EXTERNAL_STORAGE
        else
            ""

        if (ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED &&
            (permissionStorage.isEmpty() || android.os.Environment.isExternalStorageManager())) {
            // Hide permission denied UI if it's visible
            if (permissionDeniedLayout.visibility == android.view.View.VISIBLE) {
                permissionDeniedLayout.visibility = android.view.View.GONE
                loadVideos()
            }
        }
        
        if (isInBackground && currentScreen == Screen.PLAYER && currentVideoPath != null) {
            // Restore video playback
            isInBackground = false
            restoreVideoPlayback()
        }
    }
    
    override fun onStop()    { 
        super.onStop()
        // Ensure system volume is restored when app goes to background
        restoreSystemVolume()
        // Only stop video if we're not in player screen or if player is null
        if (currentScreen != Screen.PLAYER || mediaPlayer == null) {
            stopVideo() 
        }
    }
    
    override fun onDestroy() { 
        super.onDestroy()
        restoreSystemVolume()
        stopVideo() 
    }
    
    private fun restoreVideoPlayback() {
        try {
            val player = mediaPlayer ?: return
            val videoPath = currentVideoPath ?: return
            
            // Reload saved translation for the current video
            val (savedTranslationX, savedTranslationY) = getVideoTranslation(videoPath)
            currentTranslationX = savedTranslationX
            currentTranslationY = savedTranslationY
            
            // Detach views first to ensure clean state
            player.detachViews()
            
            // Re-attach views with proper parameters
            player.attachViews(vlcVideoLayout, null, true, false)
            
            // Wait a moment for surface to be ready, then restore position and playback
            handler.postDelayed({
                try {
                    // Apply saved zoom and translation
                    applyVideoZoom()
                    
                    // Restore position
                    if (currentVideoPosition > 0) {
                        player.time = currentVideoPosition
                    }
                    
                    // Resume playback if it was playing before
                    if (wasPlayingBeforeBackground) {
                        player.play()
                    }
                    
                    // Update UI
                    btnPlayPause.setImageResource(if (player.isPlaying) R.drawable.ic_pause else R.drawable.ic_play)
                    resetControlsHideTimer()
                    
                } catch (e: Exception) {
                    e.printStackTrace()
                    android.util.Log.e("OniPlayer", "Error in delayed video restoration: ${e.message}", e)
                }
            }, 100) // Small delay to ensure surface is ready
            
        } catch (e: Exception) {
            e.printStackTrace()
            android.util.Log.e("OniPlayer", "Error restoring video playback: ${e.message}", e)
        }
    }
}
