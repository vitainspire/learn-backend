import logging
import os
import subprocess
import json
from google.cloud import discoveryengine_v1alpha as discoveryengine

logger = logging.getLogger(__name__)

class NotebookLMEnterpriseClient:
    """
    A hybrid client that uses Google Cloud Discovery Engine for structural integration
    and the notebooklm-py CLI for specialized content generation (infographics).
    """
    
    def __init__(self, project_id=None, location="global"):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.location = location
        self.parent = f"projects/{self.project_id}/locations/{self.location}"
        
        # Discovery Engine clients (for structural management)
        # Note: We use specific service clients that exist in 0.17.0
        try:
            self.discovery_client = discoveryengine.EngineServiceClient()
            logger.info("Discovery Engine client initialized.")
        except Exception as e:
            logger.warning(f"Discovery Engine client initialization failed: {e}. Some features might be limited.")

    def _run_cli(self, args):
        """Helper to run the notebooklm-py CLI."""
        cmd = ["python", "-m", "notebooklm"] + args
        try:
            logger.info(f"Running CLI: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"CLI error: {e.stderr}")
            raise Exception(f"NotebookLM CLI failed: {e.stderr or e.output}")

    def create_educational_notebook(self, lesson_title, style_guide_text=None):
        """
        Creates a new notebook using the CLI as a proxy for the Enterprise API.
        """
        try:
            logger.info(f"Creating notebook: {lesson_title}")
            output = self._run_cli(["create", lesson_title])
            
            # Extract notebook ID from CLI output: "Created notebook: <UUID> - <Title>"
            notebook_id = lesson_title # Default
            if "Created notebook:" in output:
                try:
                    # Split by colon and then by space
                    parts = output.split("Created notebook:")[1].strip().split(" ")
                    if parts:
                        notebook_id = parts[0]
                        logger.info(f"Extracted notebook ID: {notebook_id}")
                except Exception as parse_err:
                    logger.warning(f"Failed to parse notebook ID from output: {parse_err}. Using title.")
            
            if style_guide_text:
                self.add_style_guide(notebook_id, style_guide_text)
                
            return notebook_id
        except Exception as e:
            logger.error(f"Failed to create notebook: {str(e)}")
            raise

    def add_style_guide(self, notebook_id, style_guide_text):
        """
        Adds a style guide as a source to the notebook.
        """
        try:
            logger.info(f"Adding style guide to notebook: {notebook_id}")
            # Sanitize notebook_id for filename
            safe_id = "".join([c if c.isalnum() else "_" for c in notebook_id])
            tmp_dir = os.path.join(os.getcwd(), ".tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            temp_file = os.path.abspath(os.path.join(tmp_dir, f"style_{safe_id}.txt"))
            
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(style_guide_text)
            
            # Use -n or --notebook for the notebook ID
            self._run_cli(["source", "add", "-n", notebook_id, temp_file])
            return True
        except Exception as e:
            logger.error(f"Failed to add style guide: {str(e)}")
            raise

    def generate_infographic(self, notebook_id, style="Professional", instructions=""):
        """
        Generates an infographic artifact, downloads it as a PNG, and returns base64 string.
        """
        import base64
        try:
            logger.info(f"Generating infographic for notebook {notebook_id} with style {style}")
            
            # Map style names to lowercase expected by CLI
            style_map = {
                "Professional": "professional", 
                "Sketch Note": "sketch-note",
                "Cartoonish": "sketch-note" # Alias
            }
            cli_style = style_map.get(style, "professional")
            
            # 1. Generate the infographic
            args = ["generate", "infographic"]
            if instructions:
                args.append(instructions)
            args += ["--notebook", notebook_id, "--style", cli_style, "--wait", "--json"]
            
            logger.info(f"Running CLI generation: {' '.join(args)}")
            gen_output = self._run_cli(args)
            
            # 2. Download the infographic
            logger.info(f"Downloading latest infographic for notebook {notebook_id}")
            
            # Use unique filename to avoid collisions
            safe_id = "".join([c if c.isalnum() else "_" for c in notebook_id])
            tmp_dir = os.path.join(os.getcwd(), ".tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            img_path = os.path.abspath(os.path.join(tmp_dir, f"info_{safe_id}.png"))
            
            # Use positional path argument
            download_args = ["download", "infographic", img_path, "--notebook", notebook_id, "--latest", "--force", "--json"]
            download_output = self._run_cli(download_args)
            
            if os.path.exists(img_path):
                logger.info(f"Image successfully downloaded to: {img_path}")
                with open(img_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                
                # Cleanup
                try: os.remove(img_path)
                except: pass
                
                # RECOVERY: Add data: prefix here if you want, but better to keep it consistent with existing frontend
                # Actually, the frontend uses src={`data:${visualGuideContent}`}
                # So if I return "image/png;base64,..." it works.
                # But what if I just return a proper data URL "data:image/png;base64,..."?
                # Then the frontend needs to handle it.
                return f"image/png;base64,{encoded_string}"
            
            logger.warning(f"Infographic not found at expected path: {img_path}. Output: {download_output}")
            return gen_output # Fallback
        except Exception as e:
            logger.error(f"Failed to generate infographic: {str(e)}")
            raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = NotebookLMEnterpriseClient()
    print("Hybrid Enterprise Client ready.")
