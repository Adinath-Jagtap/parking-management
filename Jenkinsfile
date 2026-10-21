pipeline {
    agent any

    environment {
        IMAGE_NAME = 'parkeasy'
    }

    triggers {
        githubPush()
        pollSCM('H/5 * * * *')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    python3 -m venv venv
                    . venv/bin/activate
                    pip install -q -r requirements.txt -r requirements-dev.txt
                '''
            }
        }

        stage('Build') {
            steps {
                sh '''
                    . venv/bin/activate
                    python -m py_compile app.py
                '''
            }
        }

        stage('Test') {
            steps {
                sh '''
                    . venv/bin/activate
                    TZ=UTC pytest -v --junitxml=report.xml
                '''
            }
            post {
                always {
                    junit 'report.xml'
                }
            }
        }

        stage('Docker Build') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DH_USER', passwordVariable: 'DH_PASS')]) {
                    sh '''
                        /usr/bin/docker build -t $DH_USER/$IMAGE_NAME:$BUILD_NUMBER -t $DH_USER/$IMAGE_NAME:latest .
                    '''
                }
            }
        }

        stage('Docker Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DH_USER', passwordVariable: 'DH_PASS')]) {
                    sh '''
                        echo "$DH_PASS" | /usr/bin/docker login -u "$DH_USER" --password-stdin
                        /usr/bin/docker push $DH_USER/$IMAGE_NAME:$BUILD_NUMBER
                        /usr/bin/docker push $DH_USER/$IMAGE_NAME:latest
                    '''
                }
            }
        }

        stage('Deploy') {
            steps {
                withCredentials([
                    usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DH_USER', passwordVariable: 'DH_PASS'),
                    file(credentialsId: 'parkeasy-env', variable: 'ENV_FILE')
                ]) {
                    sh '''
                        /usr/bin/docker network create devops-net || true
                        /usr/bin/docker rm -f parkeasy-app || true
                        /usr/bin/docker run -d --name parkeasy-app --network devops-net -p 5000:5000 \
                            --env-file $ENV_FILE -v parkeasy-uploads:/app/static/uploads \
                            $DH_USER/$IMAGE_NAME:latest
                        sleep 15
                        curl -f http://host.docker.internal:5000/health || echo "Health check warning - verify app manually at localhost:5000"
                    '''
                }
            }
        }
    }

    post {
        success { echo 'Pipeline finished: application deployed.' }
        failure { echo 'Pipeline failed: nothing was deployed after the failing stage.' }
    }
}
